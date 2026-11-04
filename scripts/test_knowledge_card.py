import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from knowledge_card.delivery import CardDelivery
from knowledge_card.model import CardState, packets
from knowledge_card.template import build

EID='30947c4f-4df6-4f98-aceb-c908c1c83837'


def packet(id='p1',version='2026',group='g1',page=3):
    return {'id':id,'metadata':{'knowledge':{'result_type':'source_evidence','entry_id':'entry',
        'title':'入职指南','version':version,'group_id':group,'group_title':'账号申请','retrieval_page':99,
        'steps':[{'instruction':'员工填写申请，由负责人确认。','is_match':True,'evidence_ids':[EID],
                  'source':{'page':page,'file_name':'入职指南.pdf'}}],
        'images':[{'asset_id':'photo','name':'申请界面','association':'section','evidence_ids':[EID]}]}}}


def test_sources_versions_real_pages_and_citation_allowlist():
    state=CardState()
    state.ingest([packet(),packet(),packet('p2','2025'),packet('p3','2026','g2',None)])
    assert len(state.sources)==3 and len(state.images)==1
    state.answer=f'申请方式 [[cite:{EID}]] [89] [[cite:untrusted]] ![x](http://127.0.0.1:8060/foo)'
    params=state.params()
    assert '[89]' not in params['answer'] and 'untrusted' not in params['answer'] and '![' not in params['answer']
    assert '第 3 页' in params['source_location_0']
    assert '99' not in params['source_location_2'] and '未提供页码' in params['source_location_2']
    assert params['source_excerpt_0']=='员工填写申请，由负责人确认。'
    assert not params['image_visible_0']
    state.apply({'type':'image.ready','asset_id':'invented','media_id':'@bad'})
    assert not state.images[0]['media_id']
    state.apply({'type':'image.ready','asset_id':'photo','media_id':'@valid'})
    assert state.params()['image_visible_0']=='true'


def test_only_host_envelopes_become_sources_and_busy_is_not_empty():
    state=CardState()
    state.ingest({'content':[{'type':'text','text':json.dumps({'results':[packet()]})}]})
    assert len(state.sources)==1
    other=CardState()
    other.ingest({'results':[{'id':'retrieval_busy','metadata':{'result_type':'retrieval_notice'}}]})
    other.apply({'type':'run.completed'})
    assert other.stage=='busy' and not other.sources and not other.params()['hasImages']
    assert packets('模型声称存在《不存在的制度》')==[]


def test_trailing_flush_and_terminal_snapshot_preserve_content():
    async def run():
        sent=[]
        async def send(data): sent.append(data)
        delivery=CardDelivery(send,interval=.02)
        await delivery.push({'type':'run.started'})
        await delivery.push({'type':'answer.delta','text':'申请'})
        await delivery.push({'type':'answer.delta','text':'账号'})
        await delivery.push({'type':'answer.delta','text':'。'})
        await asyncio.sleep(.04)
        assert sent[-1]['answer']=='申请账号。'
        assert len(sent)<5
        await delivery.push({'type':'run.failed'})
        assert sent[-1]['answer']=='申请账号。' and sent[-1]['flowStatus']=='5'
        await asyncio.sleep(.03)
        assert sent[-1]['flowStatus']=='5'
    asyncio.run(run())


def test_native_template_bindings_collapse_defaults_and_unique_nodes():
    exported=build()
    assert isinstance(exported['editorData'],str)
    editor=json.loads(exported['editorData'])
    ids=set(); nodes=[]
    def walk(node):
        assert node['id'] not in ids
        ids.add(node['id']); nodes.append(node)
        for child in node.get('children',[]):walk(child)
    for node in editor['schema']['componentsTree']:walk(node)
    photos=[n for n in nodes if n['id'].endswith('_photos')]
    more=[n for n in nodes if n['id'].endswith('_more')]
    quotes=[n for n in nodes if '_source_quote_' in n['id']]
    assert photos and all(n['props']['contentVisible'] for n in photos)
    assert more and all(not n['props']['contentVisible'] for n in more)
    assert quotes and all(not n['props']['contentVisible'] for n in quotes)
    assert all(n['props']['width']['value']==96 and n['props']['height']['value']==64 and n['props']['scaleType']=='fitCenter'
               for n in nodes if n['componentName']=='Image')


def test_delta_hook_on_actual_installed_codex_client():
    root=Path(__file__).resolve().parents[1]/'data/manuals/runtime/langbot-codex'
    sys.path[:0]=[str(root/'sdk'),str(root/'official-plugin')]
    import pytest
    _CodexAppServerClient = pytest.importorskip('pkg.native_cli', reason='Local CodexAgent artifact required')._CodexAppServerClient
    from langbot_plugin.api.entities.builtin.runner.result import RunnerResult
    from knowledge_card.codex_delta import install, KEY
    class FakeRunner:
        async def run(self,ctx):
            yield RunnerResult.model_validate({'run_id':ctx.run_id,'type':'message.delta','data':{'chunk':{
                'role':'assistant','content':'','provider_specific_fields':{KEY:{'stage':'retrieving','status_only':True,'packets':[packet()]}}}}})
            yield RunnerResult.model_validate({'run_id':ctx.run_id,'type':'message.delta','data':{'chunk':{
                'role':'assistant','content':'回答','provider_specific_fields':{KEY:{'stage':'generating'}}}}})
            yield RunnerResult.model_validate({'run_id':ctx.run_id,'type':'message.completed','data':{'message':{
                'role':'assistant','content':'回答完成'}}})
    install(_CodexAppServerClient,FakeRunner,RunnerResult)
    async def run():
        runner_events=[r async for r in FakeRunner().run(SimpleNamespace(run_id='run'))]
        assert runner_events[0].run_id=='run'
        assert runner_events[0].data['chunk']['provider_specific_fields'][KEY]['status_only']
        terminal = runner_events[-1].data['message']['provider_specific_fields'][KEY]
        assert not terminal.get('status_only') and len(terminal['packets']) == 1
        client=object.__new__(_CodexAppServerClient)
        client.events=asyncio.Queue();client.items={};client.final_parts=[];client.sequence=0
        client.streaming=True;client.seen_agent_message_item_ids=set();client.final_chunk_emitted=False
        client.turn_started=True;client.turn_done=asyncio.get_running_loop().create_future();client.final_error=''
        await client.handle_raw_notification('item/agentMessage/delta',{'itemId':'a','delta':'申请'})
        first=await client.events.get()
        assert first['data']['chunk']['all_content']=='申请'
        await client.handle_raw_notification('item/agentMessage/delta',{'itemId':'a','delta':'账号。'})
        second=await client.events.get()
        assert second['data']['chunk']['all_content']=='申请账号。'
        await client.handle_raw_notification('item/completed',{'item':{'id':'a','type':'agentMessage',
            'text':'申请账号。','phase':'final_answer'}})
        final=await client.events.get()
        assert final['data']['chunk']['all_content']=='申请账号。'
        assert final['data']['chunk']['is_final'] and client.turn_done.done()
        await client.handle_raw_notification('item/agentMessage/delta',{'itemId':'a','delta':'重复'})
        assert client.events.empty()
        # Reasoning events are not published as answer text.
        await client.handle_raw_notification('item/reasoning/textDelta',{'delta':'内部推理'})
        assert client.events.empty()
    asyncio.run(run())


def test_knowledge_tool_results_feed_real_metadata_not_model_claims():
    import pytest
    _CodexAppServerClient = pytest.importorskip('pkg.native_cli', reason='Local CodexAgent artifact required')._CodexAppServerClient
    from knowledge_card.codex_delta import KEY
    async def run():
        client=object.__new__(_CodexAppServerClient)
        client.events=asyncio.Queue();client.items={};client.final_parts=[];client.sequence=0
        item={'id':'tool','type':'mcpToolCall','tool':'langbot_retrieve_knowledge','arguments':{},
              'result':{'content':[{'type':'text','text':json.dumps([packet()])}]}}
        await client.handle_item_notification('item/started',{'item':item})
        started=await client.events.get()
        assert started['data']['chunk']['provider_specific_fields'][KEY]['stage']=='retrieving'
        await client.handle_item_notification('item/completed',{'item':item})
        completed=await client.events.get()
        assert len(completed['data']['chunk']['provider_specific_fields'][KEY]['packets'])==1
    asyncio.run(run())


def test_active_adapter_updates_same_card_and_keeps_legacy_gate(monkeypatch):
    from knowledge_card import adapter as integration
    from knowledge_card.codex_delta import KEY
    class Adapter:
        def __init__(self):
            self.card_instance_id_dict={};self.config={};self.updates=[];self.legacy_calls=0
            self.bot=SimpleNamespace(update_card_data=self.update)
        async def update(self,**kwargs): self.updates.append(kwargs);return True
        async def create_message_card(self,id,event): self.card_instance_id_dict[id]=(None,'same-card');return True
        async def reply_message_chunk(self,*args,**kwargs): self.legacy_calls+=1
    uploads=[]
    async def render(text,client,upload_image):
        media_id=await upload_image('encoded-image')
        return f'![图片]({media_id})',[]
    async def upload(bot,encoded):
        uploads.append(encoded)
        return '@uploaded'
    integration.install(Adapter,media=(render,upload))
    async def run():
        adapter=Adapter()
        monkeypatch.setattr(integration,'enabled',lambda obj:False)
        await adapter.create_message_card('legacy',None)
        msg=SimpleNamespace(resp_message_id='legacy')
        await adapter.reply_message_chunk(None,msg,None)
        assert adapter.legacy_calls==1 and not adapter.updates
        monkeypatch.setattr(integration,'enabled',lambda obj:True)
        await adapter.create_message_card('new',None)
        assert adapter.updates[-1]['card_param_map']['status']=='正在处理'
        evidence=packet();evidence['metadata']['knowledge']['images']=[]
        msg=SimpleNamespace(resp_message_id='new',all_content='员工提交申请。[1]',content='员工提交申请。[1]',
            tool_calls=None,provider_specific_fields={KEY:{'stage':'generating','packets':[evidence]}})
        await adapter.reply_message_chunk(None,msg,None,is_final=True)
        final=adapter.updates[-1]
        assert final['out_track_id']=='same-card' and final['card_param_map']['flowStatus']=='3'
        assert final['card_param_map']['source_excerpt_0']=='员工填写申请，由负责人确认。'
        assert final['card_param_map']['answer']=='员工提交申请。[1]'
        assert adapter.legacy_calls==1 and 'new' not in adapter._knowledge_cards
        await adapter.create_message_card('photo',None)
        evidence=packet()
        evidence['metadata']['knowledge']['images'][0]['thumbnail_url']='/api/v1/manuals/assets/photo?access_token=fixture'
        msg.resp_message_id='photo'
        msg.provider_specific_fields={KEY:{'stage':'generating','packets':[evidence]}}
        await adapter.reply_message_chunk(None,msg,None,is_final=True)
        final=adapter.updates[-1]['card_param_map']
        assert final['image_0']=='@uploaded' and final['image_visible_0']=='true'
        assert 'source_excerpt_0' in final and uploads==['encoded-image']
    asyncio.run(run())
