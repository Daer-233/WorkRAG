"""Short-lived document references owned by the LangBot Host."""
import asyncio
import base64
from collections import OrderedDict
from contextlib import aclosing
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field, replace
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import time
from uuid import UUID, uuid4
from urllib.parse import unquote

import httpx

from . import intent_host as host
from .codex_delta import KEY
from .model import packets

CONFIG = Path('/app/data/work-knowledge-session-memory.json')
TOKEN_FILE = CONFIG.with_name('work-knowledge-session-memory-token')
HOST_BOOT = str(uuid4())
from .deployment import NATIVE_AGENT
TTL = 1800
LIMIT = 1000
MEMORY = OrderedDict()
IN_FLIGHT = set()
LATEST = {}
ACTIVE = ContextVar('work_knowledge_session_memory', default=None)
RUNS = {}
LOG = logging.getLogger('work.knowledge.memory')
SHADOW_LOG = logging.getLogger('work.intent.codex2.shadow')
NATIVE_SHADOW_TASKS = set()


@dataclass(frozen=True)
class Source:
    entry_id: str
    title: str
    version: str
    cursor: str | None = None


@dataclass(frozen=True)
class Remembered:
    at: float
    anchor: str
    sources: tuple[Source, ...]
    pending: str | None = None
    offer: bool = False


@dataclass
class Followup:
    key: tuple[str, ...]
    query_id: str
    kind: str
    source: Source
    anchor: str
    event_id: str | None = None
    runs: set[str] = field(default_factory=set)
    evidence: list = field(default_factory=list)
    closed: bool = False
    turn_id: str | None = None


def enabled():
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8')).get('enabled') is True
    except (OSError, ValueError, AttributeError):
        return False


def postgres_mode():
    try:
        return json.loads(CONFIG.read_text(encoding='utf-8')).get('storage') == 'postgres'
    except (OSError, ValueError, AttributeError):
        return False


def identity(query, durable=False):
    if not host.selected(query, None) and not (durable and getattr(query, '_work_native_memory', False)):
        return None
    values = [getattr(query, field, None) for field in
              ('workspace_uuid', 'bot_uuid', 'pipeline_uuid', 'launcher_id', 'sender_id')]
    if durable:
        session = getattr(query, 'session', None)
        if not hasattr(session, '_context_generation'):
            return None
        values.append(session._context_generation or 'initial')
    else:
        values.append(host.conversation_id(query))
    if not all(value is not None and str(value).strip() for value in values):
        return None
    return tuple(str(value) for value in values)


def previous(key, now):
    for old_key, record in list(MEMORY.items()):
        if now - record.at >= TTL or (old_key[:-1] == key[:-1] and old_key != key):
            MEMORY.pop(old_key, None)
    for old_key in tuple(IN_FLIGHT):
        if old_key[:-1] == key[:-1] and old_key != key:
            LATEST.pop(old_key, None)
            IN_FLIGHT.discard(old_key)
    return MEMORY.get(key)


def save(key, record):
    MEMORY[key] = record
    MEMORY.move_to_end(key)
    while len(MEMORY) > LIMIT:
        MEMORY.popitem(last=False)


def normalized(text):
    return re.sub(r'[\s，。？！、,.!?]+', '', text.strip()).casefold()


def request_kind(text, record):
    if re.fullmatch(r'(?:那|然后)?(?:下(?:一|个)步)(?:呢|怎么做|是什么)?', text):
        return 'next_step'
    if re.fullmatch(r'(?:还有|有|有没有|给我看|我想看|发我|看看|看一下|看看刚才的)(?:刚才(?:那份)?(?:的)?|这份(?:的)?|现场(?:的)?)?(?:图|图片|照片|截图|配图)(?:吗|呢|能给我看看吗)?', text):
        return 'images'
    if re.fullmatch(r'(?:请|麻烦)?(?:把)?(?:刚才(?:那份)?(?:的)?|上一份(?:的)?|这份(?:的)?)?(?:发我|发给我|给我|需要|我要)(?:刚才(?:那份)?(?:的)?|这份(?:的)?)?(?:源文件|原文件|原件|整理稿)', text):
        return 'source_file'
    if re.fullmatch(r'(?:把)?(?:刚才那份|上一份|这份)(?:资料)?(?:的)?(?:原文件|源文件|原件)(?:发我|发给我|给我)?', text):
        return 'source_file'
    if record and record.offer and text in {'需要', '要', '发给我', '发我'}:
        return 'source_file'
    if text in {'刚才那份', '刚才那份呢', '这份呢', '上一份呢', '继续讲刚才那份'}:
        return 'context'
    return None


def choose(text, sources):
    match = re.fullmatch(r'(?:第)?([0-9]{1,2}|[一二三四五六七八九十]|十一|十二)(?:份|项|个)?', text)
    if match:
        value = match[1]
        index = int(value) if value.isascii() else '一 二 三 四 五 六 七 八 九 十 十一 十二'.split().index(value) + 1
        return True, sources[index - 1] if 1 <= index <= len(sources) else None
    matches = [source for source in sources if text in {
        normalized(source.title), normalized(f'{source.title}（{source.version}）'),
    }]
    return bool(matches), matches[0] if len(matches) == 1 else None


def choices(sources):
    lines = [f'{index}. {source.title}（{source.version or "版本未标注"}）'
             for index, source in enumerate(sources, 1)]
    return '你指的是哪一份资料？请回复序号或资料名。\n' + '\n'.join(lines)


def cited_sources(evidence, answer):
    sources = {}
    evidence = packets(evidence)
    title_ids = {}
    for packet in evidence:
        metadata = packet['metadata']
        if metadata.get('result_type') == 'source_evidence':
            title_ids.setdefault(metadata.get('title'), set()).add(str(metadata.get('entry_id')))
    for packet in evidence:
        metadata = packet['metadata']
        if metadata.get('result_type') != 'source_evidence':
            continue
        try:
            entry_id = str(UUID(str(metadata.get('entry_id'))))
        except ValueError:
            continue
        title = metadata.get('title')
        if not isinstance(title, str) or not title.strip():
            continue
        cited_steps = [str(identifier) for step in metadata.get('steps', [])
                       for identifier in step.get('evidence_ids', []) if str(identifier) in answer]
        packet_id = packet.get('id')
        named = len(title_ids[title]) == 1 and (f'《{title}》' in answer or f'【{title}】' in answer)
        if not (cited_steps or (packet_id and str(packet_id) in answer) or named):
            continue
        cursor = None
        if cited_steps:
            try:
                cursor = str(UUID(cited_steps[-1]))
            except ValueError:
                pass
        candidate = Source(entry_id, title[:300], str(metadata.get('version') or '')[:120], cursor)
        existing = sources.get(entry_id)
        if existing and existing.cursor and candidate.cursor and existing.cursor != candidate.cursor:
            # Different cited passages can belong to different procedures.
            sources[entry_id] = replace(existing, cursor=None)
        elif existing is None:
            sources[entry_id] = candidate
    return tuple(sources.values())[:12]


def final(message_class, text, stage='completed', evidence=None):
    return message_class(role='assistant', content=text, all_content=text, is_final=True,
                         provider_specific_fields={KEY: {'stage': stage, 'packets': evidence or []}})


def fresh_outcome(scope):
    evidence = packets(scope.evidence)
    valid = [packet for packet in evidence if packet['metadata']['result_type'] == 'source_evidence']
    if valid:
        if scope.kind == 'images':
            lines, shown = [], set()
            for packet in valid:
                meta = packet['metadata']
                photos = []
                for image in meta.get('images', []):
                    asset = image.get('asset_id')
                    url = image.get('preview_url') or ''
                    if not asset or asset in shown or len(shown) >= 12:
                        continue
                    if not url.startswith(('/api/v1/manuals/assets/', 'http://127.0.0.1:8060/api/v1/manuals/assets/')):
                        continue
                    name = re.sub(r'[\[\]\r\n]', '', image.get('name') or '资料配图')
                    photos.append(f'![{name}]({url})')
                    shown.add(asset)
                if photos:
                    heading = f'《{meta["title"]}》'
                    if meta.get('group_title'):
                        heading += f' · {meta["group_title"]}'
                    lines.extend([heading, *photos, ''])
            if lines:
                return '\n'.join(lines).strip(), valid, 'completed'
            return '这份资料当前没有可展示的图片。', [], 'empty'
        if scope.kind != 'source_file':
            return None, valid, 'completed'
        packet = valid[0]
        file = packet['metadata'].get('source_file') or {}
        title = packet['metadata']['title']
        if file.get('available') is not True:
            return f'《{title}》目前没有可用的源文件。', valid, 'completed'
        label = '整理稿' if file.get('kind') == 'extracted_markdown' else '源文件'
        return f'已定位《{title}》的{label}。当前钉钉助手尚未接通文件附件发送。', valid, 'completed'
    for packet in evidence:
        message = packet.get('content')
        if isinstance(message, str) and message:
            return message, [], 'busy' if packet['id'] == 'retrieval_busy' else 'empty'
    return '这次没有取得所选资料的可用依据。请重试，或明确指定要查的其他资料。', [], 'empty'


def memory_headers():
    return {'Host': '127.0.0.1:8060', 'X-Manual-Request': '1',
            'X-Session-Memory-Token': TOKEN_FILE.read_text(encoding='ascii').strip()}


async def memory_request(operation, body):
    async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
        response = await client.post(
            f'http://host.docker.internal:8060/api/v1/manuals/internal/session-memory/{operation}',
            json=body, headers=memory_headers())
        response.raise_for_status()
        return response.json()


def candidate_guard(text, attachments, has_references):
    """Identify requests that are missing an attachment or a prior reference."""
    if attachments:
        return None
    if re.search(r'(?:文件|附件|材料|文档|表格)(?:还|尚|暂时)?(?:没有|没|未)(?:传|上传|发|附)', text):
        return 'missing_attachment'
    if not has_references:
        if re.search(r'(?:左边|右边|聊天里|对话里|上面|刚才)那?(?:第[一二三四五六七八九十0-9]+)?(?:段|版|一份|份|个)', text):
            return 'missing_reference'
        if re.search(r'(?:这个|那个|刚才的)流程.{0,18}审批', text):
            return 'missing_procedure'
    return None


async def native_intent_results(results, query, message_class, decision):
    try:
        cfg = host.settings()
    except (OSError, ValueError, AttributeError):
        cfg = {}
    if getattr(query, '_work_native_memory', False) and cfg.get('native_mode') == 'on':
        text, attachments = host.incoming(query)
        reason = candidate_guard(text, attachments, decision.get('has_references', False))
        if reason:
            value = {'intent': 'clarify', 'method': reason, 'message': {
                'missing_attachment': '请先上传要处理的文件，再告诉我需要做什么。',
                'missing_reference': '请贴出你指的内容，或告诉我具体是哪份资料。',
                'missing_procedure': '请告诉我具体是哪项流程，我再核对审批要求。',
            }[reason]}
        else:
            try:
                value = await host.classify({'text': text[:4000], 'attachment_types': attachments})
                if value['mode'] not in ('shadow', 'on') or value.get('config_version') != cfg.get('version'):
                    raise ValueError('Unexpected classifier version or mode')
            except Exception as error:
                SHADOW_LOG.warning('native_intent_unavailable=%s applied=false', type(error).__name__)
                value = None
        if value:
            intent = value['intent']
            SHADOW_LOG.info('native_intent=%s method=%s elapsed_ms=%s applied=true',
                            intent, value.get('method'), value.get('elapsed_ms', 0))
            if intent == 'clarify':
                yield final(message_class, value.get('message') or '请补充具体的问题。')
                return
            scope = host.Scope(str(query.query_id), str(query.workspace_uuid), str(query.bot_uuid),
                               intent, 'image' in attachments)
            token = host.ACTIVE.set(scope)
            try:
                async with aclosing(results) as stream:
                    async for item in stream:
                        yield item
            finally:
                host.ACTIVE.reset(token)
            return
    async with aclosing(results) as stream:
        async for item in stream:
            yield item


def start_native_shadow(query, decision):
    if not getattr(query, '_work_native_memory', False):
        return None
    try:
        cfg = host.settings()
        if cfg.get('mode') != 'shadow' or cfg.get('native_mode') == 'on':
            return None
    except (OSError, ValueError):
        return None
    if len(NATIVE_SHADOW_TASKS) >= 8:
        SHADOW_LOG.info('shadow_skipped=capacity applied=false')
        return None

    text, attachments = host.incoming(query)
    action = decision['action']
    outcome = asyncio.get_running_loop().create_future()

    async def observe():
        baseline = method = 'unavailable'
        elapsed = 0
        reason = None
        if action == 'retrieve':
            baseline = {'images': 'images', 'source_file': 'source_file', 'next_step': 'knowledge',
                        'context': 'knowledge'}[decision['kind']]
            method = 'postgres_followup'
        elif action == 'reply':
            baseline = 'clarify' if decision.get('stage') != 'busy' else 'unavailable'
            method = 'postgres_clarification'
        else:
            try:
                value = await host.classify({'text': text[:4000], 'attachment_types': attachments})
                baseline, method = value['intent'], value.get('method', 'unknown')
                elapsed = value.get('elapsed_ms', 0)
            except Exception as error:
                method = type(error).__name__
            reason = candidate_guard(text, attachments, decision.get('has_references', False))
        observed, evidence = await outcome
        SHADOW_LOG.info('baseline=%s method=%s candidate=%s guard=%s elapsed_ms=%s outcome=%s evidence_returned=%s applied=false',
                        baseline, method, 'clarify' if reason else baseline, reason or '-', elapsed, observed, evidence)

    task = asyncio.create_task(observe())
    NATIVE_SHADOW_TASKS.add(task)
    task.add_done_callback(NATIVE_SHADOW_TASKS.discard)
    return outcome


async def postgres_results(results, query, message_class, key, send_file=None):
    text, attachments = host.incoming(query)
    try:
        decision = await memory_request('begin', {'identity': key, 'host_boot': HOST_BOOT,
                                                  'text': text[:4000], 'has_attachment': bool(attachments)})
        action = decision['action']
        if action not in {'ordinary', 'retrieve', 'reply'}:
            raise ValueError('Unknown session memory action')
        turn_id = str(UUID(decision['turn_id'])) if action != 'reply' else None
    except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as error:
        LOG.warning('Session memory unavailable (%s)', type(error).__name__)
        normal = normalized(text)
        reference = request_kind(normal, Remembered(0, '', (), offer=True))
        selected = re.fullmatch(r'(?:第)?(?:[0-9]{1,2}|[一二三四五六七八九十]|十一|十二)(?:份|项|个)', normal)
        if not attachments and (reference or selected):
            yield final(message_class, '暂时无法读取会话记忆，请稍后重试，或明确说明要查哪份资料。', 'busy')
        else:
            async with aclosing(native_intent_results(results, query, message_class, {})) as stream:
                async for item in host.route_results(stream, query, message_class):
                    yield item
        return
    if action == 'reply':
        shadow = start_native_shadow(query, decision)
        if shadow is not None:
            shadow.set_result(('host_reply', False))
        yield final(message_class, decision['message'], decision.get('stage', 'completed'))
        return
    scope = None
    if action == 'retrieve':
        scope = Followup(key, str(query.query_id), decision['kind'], Source(**decision['source']), '', turn_id=turn_id)
    else:
        results = native_intent_results(results, query, message_class, decision)
    shadow = start_native_shadow(query, decision)
    async for item in run_turn(results, query, message_class, key, scope, turn_id=turn_id, send_file=send_file, shadow=shadow):
        yield item


async def route_results(results, query, message_class, *, send_file=None):
    if enabled() and postgres_mode():
        key = identity(query, durable=True)
        if key is not None:
            async for item in postgres_results(results, query, message_class, key, send_file):
                yield item
        else:
            async with aclosing(native_intent_results(results, query, message_class, {})) as stream:
                async for item in host.route_results(stream, query, message_class):
                    yield item
        return
    key = identity(query) if enabled() else None
    if key is None:
        async with aclosing(native_intent_results(results, query, message_class, {})) as stream:
            async for item in host.route_results(stream, query, message_class):
                yield item
        return

    text, attachments = host.incoming(query)
    normal = normalized(text)
    record = previous(key, time.monotonic())
    kind = request_kind(normal, record) if not attachments else None
    selection, source = (choose(normal, record.sources) if record and record.pending and not attachments
                         else (False, None))
    if selection:
        kind = record.pending
    if kind and key in IN_FLIGHT:
        yield final(message_class, '上一条消息还在处理，请等它完成后再追问。', 'busy')
        return
    if kind and (record is None or not record.sources):
        yield final(message_class, '请说一下你指的是哪份资料，或重新提出原来的问题。')
        return
    if kind and source is None:
        if len(record.sources) > 1 or selection:
            save(key, replace(record, at=time.monotonic(), pending=kind))
            yield final(message_class, choices(record.sources))
            return
        source = record.sources[0]

    # Latest started ordinary turn wins. An older concurrent run cannot restore
    # stale references after a new topic or a conversation reset.
    if not kind:
        MEMORY.pop(key, None)
    ticket = object()
    LATEST[key] = ticket
    IN_FLIGHT.add(key)
    scope = Followup(key, str(query.query_id), kind, source, record.anchor) if kind else None
    async for item in run_turn(results, query, message_class, key, scope, ticket=ticket, record=record, text=text):
        yield item


async def run_turn(results, query, message_class, key, scope, *, turn_id=None, ticket=None, record=None, text='', send_file=None, shadow=None):
    kind = scope.kind if scope else None
    token = ACTIVE.set(scope)
    evidence, answer, succeeded, failed = [], '', False, False
    terminal = None
    try:
        async with aclosing(host.route_results(results, query, message_class)) as stream:
            async for item in stream:
                info = (getattr(item, 'provider_specific_fields', None) or {}).get(KEY, {})
                if info.get('stage') == 'failed':
                    failed = True
                if not info.get('status_only'):
                    value = getattr(item, 'all_content', None)
                    if isinstance(value, str):
                        answer = value
                evidence.extend(packets(info.get('packets', [])))
                if getattr(item, 'is_final', False) and not getattr(item, 'tool_calls', None):
                    terminal = item
                    succeeded = not failed and bool(answer.strip())
                    if scope or turn_id:
                        continue
                if scope and not info.get('status_only'):
                    if kind in ('source_file', 'images') or not fresh_outcome(scope)[1]:
                        continue
                yield item
        if scope:
            message, fresh, stage = fresh_outcome(scope)
            if kind == 'source_file' and turn_id and send_file and fresh:
                metadata = fresh[0]['metadata']
                if (str(metadata.get('entry_id')) == scope.source.entry_id
                        and (metadata.get('version') or '') == scope.source.version
                        and (metadata.get('source_file') or {}).get('available') is True):
                    message, stage = await send_file(turn_id, scope.source.title)
            if message is not None or terminal is None:
                answer = message or '已找到相关资料，但这次未能生成回答，请重试。'
                terminal = final(message_class, answer, stage if message else 'failed', fresh)
                succeeded = bool(fresh) and kind in ('source_file', 'images')
            evidence = fresh
    finally:
        if shadow is not None:
            shadow.set_result(('completed' if succeeded else 'incomplete', any(
                packet['metadata'].get('result_type') == 'source_evidence' for packet in evidence)))
        ACTIVE.reset(token)
        if scope:
            scope.closed = True
            for run_id in scope.runs:
                RUNS.pop(run_id, None)
        if turn_id:
            current = identity(query, durable=True) == key
            sources = cited_sources(evidence, answer) if succeeded and current else ()
            try:
                await memory_request('finish', {'turn_id': turn_id, 'sources': [asdict(source) for source in sources],
                                                'offered_file': kind != 'source_file' and any(word in answer for word in ('源文件', '原文件', '整理稿'))})
            except (httpx.HTTPError, OSError, ValueError) as error:
                LOG.warning('Session memory write failed (%s)', type(error).__name__)
        elif LATEST.get(key) is ticket:
            LATEST.pop(key, None)
            IN_FLIGHT.discard(key)
            if identity(query) == key:
                sources = cited_sources(evidence, answer) if succeeded else ()
                if sources:
                    offer = any(word in answer for word in ('源文件', '原文件', '整理稿'))
                    save(key, Remembered(time.monotonic(), record.anchor if scope else text[:600], sources, offer=offer))
                elif scope and record:
                    save(key, replace(record, at=time.monotonic(), pending=None))
    if terminal is not None and (scope or turn_id):
        yield terminal


def scoped_query(session, kb_id, query_text, top_k, filters):
    scope = RUNS.get(str(session.get('run_id'))) if session else None
    if scope is None or scope.closed:
        return query_text, top_k, filters
    if str(kb_id) != host.KB:
        raise ValueError('会话追问只允许使用工作知识库。')
    if scope.turn_id:
        envelope = json.dumps({'memory_turn': scope.turn_id})
        return '@knowledge ' + envelope + '\n会话追问', (12 if scope.kind == 'images' else 5), {}
    control = {'entry_id': scope.source.entry_id, 'version': scope.source.version,
               'followup': scope.kind, 'cursor': scope.source.cursor}
    seed = f'{scope.source.title} {scope.anchor}'.strip()
    if scope.kind == 'images':
        seed = f'{scope.source.title} 现场照片 图片 配图'
    return '@knowledge ' + json.dumps(control, ensure_ascii=False) + '\n' + seed, (12 if scope.kind == 'images' else 5), {}


def capture(session, kb_id, results):
    scope = RUNS.get(str(session.get('run_id'))) if session else None
    if scope and not scope.closed and str(kb_id) == host.KB:
        scope.evidence = packets(results)


def followup_event(event, scope):
    scope.event_id = event.event_id
    purpose = {'images': '查找入库配图', 'source_file': '核对源文件',
               'next_step': '查询原流程下一步', 'context': '继续查询原资料'}[scope.kind]
    intro = (f'[Host 会话追问] 本轮任务是{purpose}。先调用工作知识库检索，Host 会限定资料与版本。'
             '仅用本轮工具结果回答并引用资料标题或证据 ID。查图时使用结果中的媒体引用。'
             '检索无结果或繁忙时说明状态。\n[员工消息]\n')
    agent_input = event.input
    payload = agent_input.model_dump()
    payload['text'] = intro + (agent_input.text or '')
    payload['contents'].insert(0, {'type': 'text', 'text': intro})
    return event.model_copy(update={'input': type(agent_input).model_validate(payload)})


def native_intent_event(event, scope):
    scope.event_id = event.event_id
    intro = host.prompt(scope)
    if scope.intent == 'source_file':
        intro = ('[Host 本次执行范围]\n先查询已授权的工作知识库，定位用户要的资料并引用实际证据。'
                 '找到后提示用户可回复“发我原文件”，由 Host 核验并投递。\n[员工消息]\n')
        if scope.has_image:
            intro = '仅根据用户提供的文字处理，说明本轮未读取上传的图片。\n' + intro
    agent_input = event.input
    text = intro + (agent_input.text or '')
    payload = agent_input.model_dump()
    payload.update({
        'text': text, 'contents': [{'type': 'text', 'text': text}], 'attachments': [],
    })
    return event.model_copy(update={'input': type(agent_input).model_validate(payload)})


async def deliver_source_file(adapter, source, employee, turn_id, title):
    from langbot_plugin.api.entities.builtin.platform.message import File

    incoming = getattr(getattr(source, 'source_platform_object', None), 'incoming_message', None)
    if (incoming is None or str(getattr(incoming, 'conversation_type', '')) != '1'
            or not employee or str(getattr(incoming, 'sender_staff_id', '')) != employee):
        return f'无法确认《{title}》的单聊接收人，文件未发送。', 'failed'
    try:
        body = bytearray()
        async with httpx.AsyncClient(timeout=12, trust_env=False, follow_redirects=False) as client:
            async with client.stream('POST', 'http://host.docker.internal:8060/api/v1/manuals/internal/session-memory/file',
                                     json={'turn_id': turn_id}, headers=memory_headers()) as response:
                if response.status_code == 413:
                    return f'《{title}》的文件为空或超过 10 MB，无法在钉钉发送。', 'failed'
                if response.status_code in (404, 409):
                    return f'《{title}》的文件当前无法领取，请重新查询这份资料。', 'failed'
                response.raise_for_status()
                filename = unquote(response.headers['X-Session-Filename'])
                if not filename or '/' in filename or '\\' in filename:
                    raise ValueError('Invalid source filename')
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 10 * 1024 * 1024:
                        raise ValueError('Source attachment too large')
        if not body:
            raise ValueError('Empty source attachment')
        receipt = await adapter.bot.send_attachment(File(name=filename, base64=base64.b64encode(body).decode('ascii')), incoming)
        if (not isinstance(receipt, dict) or not receipt.get('processQueryKey')
                or receipt.get('invalidStaffIdList') or receipt.get('flowControlledStaffIdList')):
            raise RuntimeError('DingTalk did not confirm the recipient')
    except Exception as error:
        LOG.warning('Codex2 attachment delivery unconfirmed (%s)', type(error).__name__)
        return f'未能确认《{title}》的附件送达。请先查看当前单聊，若未收到，再回复“发我原文件”。', 'failed'
    return f'《{title}》的附件已提交到当前钉钉单聊。', 'completed'


def install_native(orchestrator_class):
    if getattr(orchestrator_class, '_work_memory_native_installed', False):
        return
    original = orchestrator_class.run
    if not SHADOW_LOG.handlers:
        try:
            handler = RotatingFileHandler('/app/data/work-knowledge-codex2-shadow.log', maxBytes=512_000,
                                          backupCount=2, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            SHADOW_LOG.addHandler(handler)
            SHADOW_LOG.setLevel(logging.INFO)
            SHADOW_LOG.propagate = False
        except OSError:
            LOG.warning('Codex2 shadow log could not be opened')

    async def run(self, event, binding, bound_plugins=None, adapter_context=None):
        context = adapter_context or {}
        adapter = context.get('_delivery_adapter')
        platform_event = context.get('_platform_event')
        target = getattr(event.delivery, 'reply_target', None) or {}
        selected = (bool(NATIVE_AGENT and host.BOT and host.KB) and binding.processor_type == 'agent' and str(binding.processor_id) == NATIVE_AGENT
                    and binding.runner_id == host.RUNNER and str(event.bot_id) == host.BOT
                    and event.source == 'platform' and event.event_type == 'message.received'
                    and target.get('target_type') == 'person' and adapter is not None
                    and type(adapter).__module__.endswith('.dingtalk.adapter') and platform_event is not None)
        if not selected:
            async for part in original(self, event, binding, bound_plugins, adapter_context):
                yield part
            return

        from langbot.pkg.agent.runner.context_reset import get_reset_generation
        from langbot.pkg.agent.runner.execution_context import build_execution_query
        from langbot_plugin.api.entities.builtin.platform import message as platform_message
        from langbot_plugin.api.entities.builtin.provider import message as provider_message

        workspace = context['_execution_context'].workspace_uuid
        if event.workspace_id and str(event.workspace_id) != workspace:
            raise ValueError('Agent event Workspace does not match its trusted ExecutionContext')
        event = event.model_copy(update={'workspace_id': workspace})
        query = build_execution_query(event, [])
        object.__setattr__(query, 'workspace_uuid', workspace)
        object.__setattr__(query, 'pipeline_uuid', NATIVE_AGENT)
        object.__setattr__(query, '_work_native_memory', True)
        persistence = self.ap.persistence_mgr
        generation = await get_reset_generation(persistence.get_db_engine(), workspace, event.bot_id, event.conversation_id)
        object.__setattr__(query.session, '_context_generation', generation)

        async def results():
            scope = ACTIVE.get()
            intent = host.ACTIVE.get()
            current = followup_event(event, scope) if scope else event
            if scope is None and intent and intent.query_id == str(query.query_id):
                current = native_intent_event(event, intent)
            async for part in original(self, current, binding, bound_plugins, adapter_context):
                if isinstance(part, provider_message.Message) and not isinstance(part, provider_message.MessageChunk):
                    value = part.content
                    if isinstance(value, list):
                        value = ''.join(item.text or '' for item in value if item.type == 'text')
                    part = provider_message.MessageChunk(role='assistant', content=value or '',
                        all_content=value or '', is_final=True,
                        provider_specific_fields=getattr(part, 'provider_specific_fields', None) or {})
                yield part

        source = getattr(platform_event, 'legacy_event', None) or platform_event
        async def send_file(turn_id, title):
            try:
                current = await get_reset_generation(persistence.get_db_engine(), workspace, event.bot_id, event.conversation_id)
            except Exception as error:
                LOG.warning('Codex2 attachment context unavailable (%s)', type(error).__name__)
                return '暂时无法确认当前会话，文件未发送。请重新查询资料。', 'failed'
            if current != generation:
                return '当前会话已重置，文件未发送。请重新查询资料。', 'failed'
            return await deliver_source_file(adapter, source, str(query.sender_id), turn_id, title)
        message_id = str(uuid4())
        card = await adapter.is_stream_output_supported()
        if card:
            await adapter.create_message_card(message_id, source)

        async def deliver(text, is_final, fields):
            chain = platform_message.MessageChain([platform_message.Plain(text=text)])
            if card:
                chunk = provider_message.MessageChunk(role='assistant', content=text, all_content=text,
                    resp_message_id=message_id, is_final=is_final, provider_specific_fields=fields)
                await adapter.reply_message_chunk(source, chunk, chain, is_final=is_final)
            elif is_final:
                await adapter.reply_message(source, chain)

        if card:
            await deliver('正在处理', False, {KEY: {'stage': 'processing', 'status_only': True}})
        latest = ''
        final_sent = False
        try:
            async with aclosing(route_results(results(), query, provider_message.MessageChunk, send_file=send_file)) as stream:
                async for part in stream:
                    fields = getattr(part, 'provider_specific_fields', None) or {}
                    status = fields.get(KEY, {})
                    value = getattr(part, 'all_content', None) or getattr(part, 'content', None)
                    if isinstance(value, str) and not status.get('status_only'):
                        latest = value
                    is_final = bool(getattr(part, 'is_final', False)) and not getattr(part, 'tool_calls', None)
                    if not final_sent and (card or is_final):
                        await deliver(latest, is_final, fields)
                        final_sent = is_final
                    yield part
            if not final_sent:
                await deliver(latest or '这次没有生成可显示的回答，请重试。', True, {KEY: {'stage': 'completed'}})
        except Exception:
            if not final_sent and card:
                try:
                    await deliver(latest or '处理失败，请稍后重试。', True, {KEY: {'stage': 'failed'}})
                except Exception:
                    LOG.warning('Codex2 error card could not be closed')
            raise

    orchestrator_class.run = run
    orchestrator_class._work_memory_native_installed = True


def install(bridge_class, builder_class, registry_class):
    if getattr(bridge_class, '_work_memory_installed', False):
        return
    build_plan = bridge_class.build_plan
    build_resources = builder_class.build_resources_from_binding
    register = registry_class.register

    def plan(self, query):
        result = build_plan(self, query)
        scope = ACTIVE.get()
        if not scope or scope.query_id != str(query.query_id) or scope.key != identity(query, durable=bool(scope.turn_id)):
            return result
        return replace(result, event=followup_event(result.event, scope))

    async def resources(self, execution_context, event, binding, descriptor, tool_catalog=None):
        result = await build_resources(self, execution_context, event, binding, descriptor, tool_catalog)
        scope = ACTIVE.get()
        if (scope and scope.event_id == event.event_id and scope.key[0] == str(event.workspace_id)
                and scope.key[1] == str(event.bot_id) and str(binding.processor_id) == scope.key[2]
                and binding.runner_id == host.RUNNER):
            return host.filter_resources(result, 'knowledge')
        intent = host.ACTIVE.get()
        if (intent and intent.event_id == event.event_id and intent.workspace == str(event.workspace_id)
                and intent.bot == str(event.bot_id) and binding.processor_type == 'agent'
                and str(binding.processor_id) == NATIVE_AGENT and binding.runner_id == host.RUNNER):
            return host.filter_resources(result, intent.intent)
        return result

    async def register_run(self, *args, **kwargs):
        scope = ACTIVE.get()
        if scope is None:
            return await register(self, *args, **kwargs)
        query = kwargs.get('execution_query')
        query_key = identity(query, durable=bool(scope.turn_id)) if query is not None else None
        if query is not None and scope.key[2] == NATIVE_AGENT:
            matches = (str(query.launcher_id), str(query.sender_id)) == scope.key[3:5]
            query_key = scope.key if matches else None
        if not (not scope.closed and scope.event_id and query is not None
                and scope.query_id == str(query.query_id) and scope.key == query_key
                and kwargs.get('runner_id') == host.RUNNER
                and str(kwargs.get('workspace_id')) == scope.key[0]
                and str(kwargs.get('bot_id')) == scope.key[1]):
            raise RuntimeError('会话追问无法绑定到已验证的工作助手运行。')
        result = await register(self, *args, **kwargs)
        run_id = str(kwargs['run_id'])
        RUNS[run_id] = scope
        scope.runs.add(run_id)
        return result

    bridge_class.build_plan = plan
    builder_class.build_resources_from_binding = resources
    registry_class.register = register_run
    bridge_class._work_memory_installed = True
