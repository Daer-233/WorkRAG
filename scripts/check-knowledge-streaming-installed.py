"""Container smoke check with the actual adapter/SDK; no platform sends."""
import asyncio
import json
from types import SimpleNamespace

from langbot.pkg.platform.adapters.dingtalk.adapter import DingTalkAdapter
from langbot.pkg.platform.adapters.dingtalk.knowledge_card.codex_delta import KEY
from langbot.pkg.platform.adapters.dingtalk.knowledge_card.streaming import prime, PIPELINE
from langbot_plugin.api.entities.builtin.provider.message import MessageChunk
from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain


async def main():
    sends=[]
    class Bot:
        async def create_and_card(self,*args,**kwargs):
            return {},'one-card'
        async def send_card_message(self,instance,id,content,final):
            sends.append((id,content,final))
    adapter=DingTalkAdapter.model_construct(config={'card_template_id':'fixture','markdown_card':True},
        bot=Bot(),card_instance_id_dict={})
    source=SimpleNamespace(source_platform_object=SimpleNamespace(incoming_message=SimpleNamespace()))
    await adapter.create_message_card('reply',source)
    ran=[]
    async def underlying():
        ran.append(True)
        yield MessageChunk(role='assistant',content='答',all_content='答',
            provider_specific_fields={KEY:{'stage':'generating'}})
    stream=prime(underlying(),SimpleNamespace(pipeline_uuid=PIPELINE),MessageChunk)
    ack=await anext(stream)
    assert not ran
    ack.resp_message_id='reply'
    await adapter.reply_message_chunk(source,ack,MessageChain([Plain(text='')]))
    assert sends[-1][1]=='正在处理'
    for stage in ('retrieving','generating'):
        chunk=MessageChunk(role='assistant',content='',all_content='',resp_message_id='reply',
            provider_specific_fields={KEY:{'stage':stage,'status_only':True}})
        await adapter.reply_message_chunk(source,chunk,MessageChain([Plain(text='')]))
    first=await anext(stream); first.resp_message_id='reply'
    await adapter.reply_message_chunk(source,first,MessageChain([Plain(text='答')]))
    first.content=first.all_content='答案。![图片](@media_fixture)'
    await adapter.reply_message_chunk(source,first,MessageChain([Plain(text=first.content)]),is_final=True)
    await stream.aclose()
    assert all(item[0]=='one-card' for item in sends)
    assert sends[-1][2] and '![图片](@media_fixture)' in sends[-1][1]
    assert 'reply' not in adapter.card_instance_id_dict
    print(json.dumps({'actual_adapter':True,'immediate_ack':True,'status_events':True,
        'same_card':True,'final_inline_media_preserved':True,'platform_sends':0}))


asyncio.run(main())
