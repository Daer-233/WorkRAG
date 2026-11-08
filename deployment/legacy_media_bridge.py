"""Legacy native-card media, gated on a published media-capable template."""
import base64
import json
import time
from pathlib import Path
from langbot_plugin.api.entities.builtin.platform.message import Image,File,MessageChain

CONFIG=Path('/app/data/workrag-legacy-media-config.json')

def settings():return json.loads(CONFIG.read_text()) if CONFIG.exists() else {}

def record(value):
    try:
        with Path('/app/data/workrag-native-media-events.jsonl').open('a') as f:f.write(json.dumps({'time':time.time(),**value})+'\n')
    except OSError:pass


def install_client(cls):
    if getattr(cls,'_workrag_file_guard',False):return
    original=cls.send_attachment;original_card=cls.send_card_message
    async def send_card(self,card,track,content,final):
        options=settings();started=time.monotonic()
        # The user's existing export uses ordinary answer variables in states
        # 2/4, but a streaming answer component in state 3. Populate that
        # component before switching to 3; do not double-write every delta.
        if (self.key==options.get('client_id') and options.get('answer_streaming_component') is True
            and final
            and not (isinstance(card,dict) and (card.get('workrag_a2ui') or card.get('workrag_plain')))):
            from langbot.libs.dingtalk_api.api import card_text_fields
            answer=card_text_fields(content)['answer']
            if answer and not await self.streaming_update_card(out_track_id=track,content_key='answer',content_value=answer,append=False,finished=final):
                raise RuntimeError('Failed to update the template streaming-answer channel')
        result=await original_card(self,card,track,content,final)
        if self.key==options.get('client_id'):
            record({'type':'card_text_update','final':bool(final),'characters':len(content),
                    'duration_ms':round((time.monotonic()-started)*1000),
                    'platform_update_accepted':True})
        return result
    async def send(self,component,incoming):
        value=await original(self,component,incoming)
        options=settings()
        if self.key==options.get('client_id') and incoming.sender_staff_id==options.get('private_tester'):
            counts={k:len(value.get(k) or []) for k in ('flowControlledStaffIdList','invalidStaffIdList','filteredStaffIdList')} if isinstance(value,dict) else {}
            rejected=any(counts.values());record({'type':'file' if isinstance(component,File) else 'image','accepted':not rejected,'rejection_counts':counts})
            if rejected:raise RuntimeError('DingTalk rejected the attachment recipient; not delivered')
        return value
    cls.send_attachment=send;cls.send_card_message=send_card;cls._workrag_file_guard=True


def install_adapter(cls):
    if getattr(cls,'_workrag_folded_media',False):return
    original=cls.reply_message_chunk
    async def reply(self,message_source,bot_message,message,quote_origin=False,is_final=False):
        options=settings();incoming=getattr(message_source.source_platform_object,'incoming_message',None)
        enabled=(options.get('folded_template_published') is True and
                 self.config.get('card_template_id')==options.get('template_id') and
                 self.config.get('client_id')==options.get('client_id') and incoming is not None and
                 incoming.sender_staff_id==options.get('private_tester'))
        images=[p for p in message if isinstance(p,Image)]
        if enabled and is_final and images and not bot_message.tool_calls:
            if len(images)>3:raise ValueError('At most 3 images per card')
            card=self.card_instance_id_dict.get(bot_message.resp_message_id)
            if card is None:raise RuntimeError('No active card for image delivery')
            token=await self.bot.get_legacy_access_token()
            if not token:raise RuntimeError('Image upload authentication failed')
            params={'workrag_has_images':'true'}
            for i,image in enumerate(images):
                encoded=getattr(image,'base64',None)
                if not encoded or len(encoded)>16*1024*1024:raise ValueError('Only bounded in-memory images are accepted')
                binary=base64.b64decode(encoded.split(',',1)[-1],validate=True)
                async with self.bot._http_client_context() as http:
                    r=await http.post('https://oapi.dingtalk.com/media/upload',params={'access_token':token,'type':'image'},
                                      files={'media':('workrag-image.png',binary)},timeout=30)
                result=self.bot._check_send_result(r);media=result.get('media_id')
                if not media:raise RuntimeError('No image media ID returned')
                params[f'workrag_image_{i}']=media;params[f'workrag_image_visible_{i}']='true'
            message=MessageChain([p for p in message if not isinstance(p,Image)])
            result=await original(self,message_source,bot_message,message,quote_origin=quote_origin,is_final=is_final)
            # Preserve final text when the platform treats cardParamMap as a
            # full replacement. Apply media after the ordinary final update.
            from langbot.pkg.platform.adapters.dingtalk.message_converter import DingTalkMessageConverter
            from langbot.libs.dingtalk_api.api import card_text_fields
            text,_=await DingTalkMessageConverter.yiri2target(message,self.config.get('markdown_card',False))
            fields=card_text_fields(text);fields.update(content=text,flowStatus='3',**params)
            if not await self.bot.update_card_data(out_track_id=card[1],card_param_map=fields):raise RuntimeError('Failed to attach images to card')
            record({'type':'folded_images','count':len(images),'platform_update_accepted':True,'client_verified':False})
            return result
        return await original(self,message_source,bot_message,message,quote_origin=quote_origin,is_final=is_final)
    cls.reply_message_chunk=reply;cls._workrag_folded_media=True
