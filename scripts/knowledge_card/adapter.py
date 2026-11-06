"""Optional adapter integration. No effect unless a validated template ID matches."""
import asyncio
import json
from pathlib import Path
import re

from .delivery import CardDelivery
from .codex_delta import KEY

CONFIG = Path('/app/data/work-knowledge-card-v1.json')


def enabled(adapter):
    try:
        data = json.loads(CONFIG.read_text())
        return data.get('validated') is True and data.get('template_id') == adapter.config.get('card_template_id')
    except (OSError,ValueError):
        return False


def install(adapter_class, media=None):
    if getattr(adapter_class,'_knowledge_card_v1_installed',False): return
    create = adapter_class.create_message_card
    reply = adapter_class.reply_message_chunk

    async def create_card(self,message_id,event):
        result = await create(self,message_id,event)
        if enabled(self):
            if not hasattr(self,'_knowledge_cards'): self._knowledge_cards = {}
            card_id = self.card_instance_id_dict[message_id][1]
            async def send(params):
                ok = await self.bot.update_card_data(out_track_id=card_id,card_param_map=params)
                if ok is False: raise RuntimeError('Knowledge card update failed')
            delivery = CardDelivery(send)
            self._knowledge_cards[message_id] = delivery
            await delivery.push({'type':'run.started'})
        return result

    async def chunk(self,message_source,bot_message,message,quote_origin=False,is_final=False):
        message_id = bot_message.resp_message_id
        delivery = getattr(self,'_knowledge_cards',{}).get(message_id)
        if delivery is None:
            return await reply(self,message_source,bot_message,message,quote_origin=quote_origin,is_final=is_final)
        info = (getattr(bot_message,'provider_specific_fields',None) or {}).get(KEY,{})
        stage = info.get('stage')
        if info.get('business'): await delivery.push({'type':'business.updated'})
        if stage in ('payment_reading','payment_preparing','payment_review','payment_ready'):
            await delivery.push({'type':'payment.stage','stage':stage})
        if stage == 'retrieving': await delivery.push({'type':'retrieval.started'})
        if stage == 'generating': await delivery.push({'type':'generation.started'})
        if info.get('packets'): await delivery.push({'type':'retrieval.completed','results':info['packets']})
        if not info.get('status_only'):
            text = getattr(bot_message,'all_content',None)
            if text is None: text = bot_message.content or ''
            await delivery.push({'type':'answer.snapshot','text':text})
        if stage == 'failed':
            await delivery.push({'type':'run.failed'})
        elif is_final and bot_message.tool_calls is None:
            try:
                if delivery.state.images:
                    if media is None:
                        from ..knowledge_media import render, upload_for_card
                    else:
                        render, upload_for_card = media
                    import httpx
                    await delivery.push({'type':'images.started'})
                    async with httpx.AsyncClient() as client:
                        for image in delivery.state.images:
                            async def upload(encoded): return await upload_for_card(self.bot,encoded)
                            url = image.get('thumbnail_url')
                            if not url:
                                await delivery.push({'type':'image.failed'})
                                continue
                            text,_ = await render(f'![图片]({url})',client,upload_image=upload)
                            match = re.search(r'!\[[^\]]*\]\((@?[\w-]+)\)',text)
                            if match: await delivery.push({'type':'image.ready','asset_id':image['asset_id'],'media_id':match[1]})
                            else: await delivery.push({'type':'image.failed'})
                if not delivery.state.sources and not delivery.state.business:
                    delivery.state.notices.append('本次未提供可核对的知识库依据。')
                await delivery.push({'type':'run.completed'})
            except BaseException:
                if not delivery.closed: await delivery.cancel()
                raise
        if delivery.closed:
            self._knowledge_cards.pop(message_id,None)
            self.card_instance_id_dict.pop(message_id,None)
    adapter_class.create_message_card = create_card
    adapter_class.reply_message_chunk = chunk
    adapter_class._knowledge_card_v1_installed = True
