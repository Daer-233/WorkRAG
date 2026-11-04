import asyncio
from types import SimpleNamespace

from knowledge_card.codex_delta import KEY
from knowledge_card.streaming import prime, install, fail_card, PIPELINE


def test_host_ack_before_runner_is_started_and_scoped():
    async def run():
        started=[]
        async def results():
            started.append(True)
            yield 'answer'
        def message(**data): return SimpleNamespace(**data)
        stream=prime(results(),SimpleNamespace(pipeline_uuid=PIPELINE),message)
        ack=await anext(stream)
        assert ack.content=='正在处理' and not started
        assert await anext(stream)=='answer' and started
        other=[x async for x in prime(results(),SimpleNamespace(pipeline_uuid='other'),message)]
        assert other==['answer']
    asyncio.run(run())


def adapter_fixture():
    class Message(SimpleNamespace):
        def model_copy(self,update): return Message(**{**vars(self),**update})
    class Adapter:
        def __init__(self):
            self.config={}; self.card_instance_id_dict={'one':(None,'same-card'),'two':(None,'second-card')}
            self.sent=[]; self._card_last_updates={}
        async def reply_message_chunk(self,source,bot,message,quote_origin=False,is_final=False):
            self.sent.append((bot.resp_message_id,bot.content,is_final))
            if is_final: self.card_instance_id_dict.pop(bot.resp_message_id)
    install(Adapter,lambda **x:SimpleNamespace(**x),list)
    def msg(text='',stage='processing',status_only=False,id='one'):
        return Message(resp_message_id=id,content=text,all_content=text,tool_calls=None,
            provider_specific_fields={KEY:{'stage':stage,'status_only':status_only}})
    return Adapter,Message,msg


def test_real_status_trailing_incremental_and_final_keep_same_card():
    async def run():
        Adapter,_,msg=adapter_fixture(); adapter=Adapter()
        await adapter.reply_message_chunk(None,msg(status_only=True),[])
        assert adapter.sent==[('one','正在处理',False)]
        await adapter.reply_message_chunk(None,msg(stage='retrieving',status_only=True),[])
        assert adapter.sent[-1][1]=='正在检索资料'
        await adapter.reply_message_chunk(None,msg(stage='generating',status_only=True),[])
        assert adapter.sent[-1][1]=='正在生成回答'
        await adapter.reply_message_chunk(None,msg('申','generating'),[])
        await adapter.reply_message_chunk(None,msg('申请账号。','generating'),[])
        assert adapter.sent[-1][1]=='正在生成回答'
        await asyncio.sleep(.55)
        assert adapter.sent[-1][1]=='正在生成回答\n\n申请账号。'
        await adapter.reply_message_chunk(None,msg('申请账号。![图片](@media)','generating'),[],is_final=True)
        assert adapter.sent[-1]==('one','回答完成\n\n申请账号。![图片](@media)',True)
        assert set(x[0] for x in adapter.sent)=={'one'} and not adapter._work_streams
        total=len(adapter.sent)
        await asyncio.sleep(.55)
        assert len(adapter.sent)==total
    asyncio.run(run())


def test_host_error_closes_original_card_and_keeps_partial_answer():
    async def run():
        Adapter,Message,msg=adapter_fixture(); adapter=Adapter()
        await adapter.reply_message_chunk(None,msg('有效片段','generating'),[])
        await adapter.reply_message_chunk(None,msg(id='two',status_only=True),[])
        query=SimpleNamespace(pipeline_uuid=PIPELINE,adapter=adapter,message_event=None)
        assert await fail_card(query,'one',Message,lambda **x:SimpleNamespace(**x),list)
        assert '有效片段' in adapter.sent[-1][1] and '失败' in adapter.sent[-1][1]
        assert 'one' not in adapter._work_streams and 'two' in adapter._work_streams
        assert not await fail_card(query,'one',Message,lambda **x:SimpleNamespace(**x),list)
    asyncio.run(run())


def test_repeated_provider_tokens_and_final_snapshot():
    import sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'data/manuals/runtime/langbot-codex'
    sys.path[:0]=[str(root/'sdk'),str(root/'official-plugin')]
    import pytest
    _CodexAppServerClient = pytest.importorskip('pkg.native_cli', reason='Local CodexAgent artifact required')._CodexAppServerClient
    from knowledge_card.codex_delta import install as install_delta
    install_delta(_CodexAppServerClient)
    async def run():
        client=object.__new__(_CodexAppServerClient)
        client.events=asyncio.Queue();client.items={};client.final_parts=['进展说明'];client.sequence=0
        client.streaming=True;client.seen_agent_message_item_ids=set();client.final_chunk_emitted=False
        client.turn_started=True;client.turn_done=asyncio.get_running_loop().create_future();client.final_error=''
        await client.handle_raw_notification('item/started',{'item':{'id':'a','type':'agentMessage','phase':'final_answer'}})
        for token in ['哈','哈']:
            await client.handle_raw_notification('item/agentMessage/delta',{'itemId':'a','delta':token})
        await client.events.get()
        assert (await client.events.get())['data']['chunk']['all_content']=='哈哈'
        await client.handle_raw_notification('item/completed',{'item':{'id':'a','type':'agentMessage','text':'哈哈','phase':'final_answer'}})
        assert (await client.events.get())['data']['chunk']['all_content']=='哈哈'
        assert client.turn_done.done()
    asyncio.run(run())


def test_busy_notice_stays_visible_on_terminal_answer():
    async def run():
        Adapter,_,msg=adapter_fixture();adapter=Adapter()
        busy=msg(stage='generating',status_only=True)
        busy.provider_specific_fields[KEY]['packets']=[{'id':'retrieval_busy',
            'metadata':{'result_type':'retrieval_notice'}}]
        await adapter.reply_message_chunk(None,busy,[])
        await adapter.reply_message_chunk(None,msg('请稍后重试。','generating'),[],is_final=True)
        assert '知识库正忙' in adapter.sent[-1][1] and '回答完成' not in adapter.sent[-1][1]
    asyncio.run(run())
