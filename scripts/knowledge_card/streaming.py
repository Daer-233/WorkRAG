"""Immediate Host acknowledgement and streaming bridge for the current template.

New structured templates keep using adapter.py. This bridge never changes the
cloud template or bypasses Host authorization, and reuses final media delivery.
"""
import asyncio
from dataclasses import dataclass, field
import time

from .codex_delta import KEY
from .model import LABELS, packets

PIPELINE = '46b1174d-a808-46e3-ace9-ce34432803db'


def selected(query):
    return str(getattr(query, 'pipeline_uuid', '')) == PIPELINE


async def prime(results, query, message_class):
    """Yield before even starting Runner context, daemon or model setup."""
    if selected(query):
        yield message_class(role='assistant', content='正在处理', all_content='',
            provider_specific_fields={KEY: {'stage':'processing', 'status_only':True}})
    try:
        from .session_memory import route_results
        async for result in route_results(results,query,message_class):
            yield result
    finally:
        close = getattr(results,'aclose',None)
        if close:
            await close()


@dataclass
class Stream:
    answer: str = ''
    stage: str = 'processing'
    last: float = 0
    pending: object = None
    lock: object = field(default_factory=asyncio.Lock)
    closed: bool = False
    error: object = None


def install(adapter_class, plain_class, chain_class):
    if getattr(adapter_class, '_work_stream_installed', False):
        return
    original = adapter_class.reply_message_chunk

    async def chunk(self, message_source, bot_message, message, quote_origin=False, is_final=False):
        from .adapter import enabled
        info = (getattr(bot_message,'provider_specific_fields',None) or {}).get(KEY)
        if enabled(self) or not info:
            return await original(self,message_source,bot_message,message,
                quote_origin=quote_origin,is_final=is_final)
        message_id = bot_message.resp_message_id
        states = getattr(self,'_work_streams',None)
        if states is None:
            self._work_streams = states = {}
        state = states.setdefault(message_id,Stream())
        if state.error:
            raise state.error
        previous = state.stage
        stage = info.get('stage')
        if stage in LABELS and (stage != 'generating' or state.stage not in ('busy','empty')):
            state.stage = stage
        notices=[p for p in packets(info.get('packets',[]))
                 if p['metadata'].get('result_type')=='retrieval_notice']
        if notices:
            state.stage = 'busy' if any(p.get('id')=='retrieval_busy' for p in notices) else 'empty'
        if not info.get('status_only'):
            text = getattr(bot_message,'all_content',None)
            if text is None:
                text = bot_message.content
            if isinstance(text,str):
                state.answer = text
        final = is_final and not getattr(bot_message,'tool_calls',None)
        if final and state.stage not in ('failed','busy','empty'):
            state.stage = 'completed'

        async def flush(terminal=False):
            async with state.lock:
                if state.closed:
                    return
                # Keep the status visible for templates binding only content or
                # answer. The new template has a separate status variable.
                text = f"{LABELS[state.stage]}\n\n{state.answer}".strip()
                visible = bot_message.model_copy(update={'content':text,'all_content':text})
                # Our trailing writer owns throttling; do not lose its last token
                # to the original adapter's leading-only throttle.
                getattr(self,'_card_last_updates',{}).pop(message_id,None)
                await original(self,message_source,visible,chain_class([plain_class(text=text)]),
                    quote_origin=quote_origin,is_final=terminal)
                state.last = time.monotonic()
                if terminal:
                    state.closed = True
                    states.pop(message_id,None)

        async def later():
            try:
                await asyncio.sleep(max(0,.5-(time.monotonic()-state.last)))
                await flush()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.error = exc

        immediate = final or previous != state.stage or not state.last
        if immediate:
            if state.pending:
                # Never cancel an HTTP update that has already started. Wait
                # for it to settle before the terminal authoritative snapshot.
                await state.pending
                state.pending = None
            await flush(final)
        elif not state.pending or state.pending.done():
            state.pending = asyncio.create_task(later())

    adapter_class.reply_message_chunk = chunk
    adapter_class._work_stream_installed = True


async def fail_card(query, message_id, message_class, plain_class, chain_class):
    """Close the same visible card when Host fails before/during Runner start."""
    if not selected(query) or message_id not in getattr(query.adapter,'card_instance_id_dict',{}):
        return False
    state = getattr(query.adapter,'_work_streams',{}).get(message_id)
    answer = state.answer if state else ''
    value = message_class(role='assistant', content=answer, all_content=answer,
        resp_message_id=message_id, is_final=True,
        provider_specific_fields={KEY:{'stage':'failed','status_only':True}})
    await query.adapter.reply_message_chunk(query.message_event,value,
        chain_class([plain_class(text=answer)]),is_final=True)
    return True
