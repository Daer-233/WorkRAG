import asyncio
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
from dotenv import load_dotenv
load_dotenv(ROOT/'instances/manuals/.env',override=True)
from app.manuals.intent import engine
from app.manuals.intent.bm25 import BM25,accepted,ranking,tokenize
from app.manuals.intent.nli import BertWorker,entailment_index
from app.manuals.intent.terra import TerraClassifier,parse_output
from app.manuals.intent.types import RouteRequest,axes_for_intent,context_text
from knowledge_card import intent_host as host


def test_bm25_compares_distinct_intents_and_keeps_identifiers():
    samples=[{'text':'安装 Office 2025 错误 0x80070005','intent':'knowledge'},
             {'text':'Office 2025 安装错误','intent':'knowledge'},
             {'text':'解释 Python','intent':'daily'}]
    terms=tokenize('Office 2025 0x80070005 gpt-6.1 IT 公司考勤')
    assert {'office','2025','0x80070005','gpt-6.1','it','公司','司考','考勤'}<=set(terms)
    values=BM25(samples).scores('Office 2025 安装错误')
    label,score,gap=ranking(values)
    assert label=='knowledge' and gap==score-values['daily']
    assert accepted(values,{'knowledge':{'score':score,'margin':gap}})
    assert not accepted(values,{})


def test_nli_never_guesses_entailment_index():
    assert entailment_index(NS(id2label={'0':'ENTAILMENT','1':'NEUTRAL'}))==0
    with pytest.raises(ValueError):entailment_index(NS(id2label={0:'LABEL_0'}))
    with pytest.raises(ValueError):entailment_index(NS(id2label={0:'ENTAILMENT',1:'entail'}))


def test_timeout_kills_worker_and_busy_never_queues():
    class Process:
        alive=True
        def is_alive(self):return self.alive
        def kill(self):self.alive=False
        def terminate(self):self.alive=False
        def join(self,timeout):pass
    class Pipe:
        def send(self,value):pass
        def poll(self,timeout):return False
        def close(self):pass
    worker=BertWorker('unused');process=Process();worker.process=process;worker.pipe=Pipe();worker.ready=True
    with pytest.raises(TimeoutError):worker.classify('question',timeout=.01)
    assert not process.alive and not worker.ready and worker.process is None
    worker.lock.acquire()
    try:
        with pytest.raises(RuntimeError,match='nli_busy'):worker.classify('q')
    finally:worker.lock.release()


def test_schema_disallows_employee_route_and_context_starts_with_question():
    with pytest.raises(ValidationError):RouteRequest(text='你好',intent='daily')
    with pytest.raises(ValidationError):RouteRequest(text='你好',knowledge_base='design')
    req=RouteRequest(text='当前公司问题',history=[{'role':'user','text':'旧问题'}])
    assert context_text(req).startswith('当前消息：当前公司问题')


def test_image_and_file_context_are_metadata_not_model_claims():
    assert engine.direct(RouteRequest(attachment_types=['image']))==('clarify','image_text_missing')
    assert engine.direct(RouteRequest(text='你好，补卡怎么申请')) is None
    assert engine.direct(RouteRequest(text='需要'))==('clarify','missing_file_context')
    source={'entry_id':'00000000-0000-4000-8000-000000000001','title':'考勤规范'}
    req=RouteRequest(text='需要',previous_sources=[source],previous_file_offer=True)
    assert engine.direct(req)==('source_file','previous_file_offer')
    req.previous_sources.append(req.previous_sources[0].model_copy(update={'title':'其他资料'}))
    assert engine.direct(req)==('clarify','choose_source')


def test_terra_invalid_outputs_and_single_failure_are_clarification(monkeypatch):
    for raw in ('{"intent":"admin"}','{"intent":"daily","tool":"search"}','```json\n{}\n```'):
        with pytest.raises((ValueError,TypeError)):parse_output(raw)
    calls=[]
    class Terra:
        async def classify(self,req):calls.append(req.text);raise TimeoutError()
    monkeypatch.setattr(engine,'config',lambda:{'mode':'shadow','version':'test','model_path':'unused','terra_enabled':True})
    monkeypatch.setattr(engine,'calibration_valid',lambda cfg:None)
    async def run():
        router=engine.Router();router.terra=Terra()
        async def warm():pass
        router.warm=warm
        value=await router.route(RouteRequest(text='情况复杂，需要分类'))
        assert value.intent=='clarify' and value.method=='fallback' and 'TimeoutError' in value.reason
    asyncio.run(run());assert len(calls)==1


def test_failed_gates_cannot_activate_and_off_does_no_inference(monkeypatch):
    cfg={'mode':'on','version':'test','model_path':'unused','terra_enabled':False}
    monkeypatch.setattr(engine,'config',lambda:cfg)
    monkeypatch.setattr(engine,'activation_valid',lambda cfg:False)
    monkeypatch.setattr(engine,'calibration_valid',lambda cfg:None)
    async def run():
        router=engine.Router()
        async def warm():pass
        router.warm=warm
        assert (await router.route(RouteRequest())).mode=='shadow'
        cfg['mode']='off'
        value=await router.route(RouteRequest(text='随便指定 daily'))
        assert value.method=='off' and value.intent is None
    asyncio.run(run())


def test_new_named_file_does_not_reuse_previous_source(monkeypatch):
    monkeypatch.setattr(engine,'config',lambda:{'mode':'shadow','version':'test','model_path':'unused','terra_enabled':True})
    monkeypatch.setattr(engine,'calibration_valid',lambda cfg:None)
    seen=[]
    class Terra:
        async def classify(self,request):seen.append(request);return axes_for_intent('source_file')
    async def run():
        router=engine.Router();router.terra=Terra()
        async def warm():pass
        router.warm=warm
        source={'entry_id':'00000000-0000-4000-8000-000000000001','title':'旧考勤规范','available':True}
        value=await router.route(RouteRequest(text='发我新的电脑借用单文件',previous_sources=[source],previous_file_offer=True))
        assert value.intent=='source_file' and '旧考勤规范' not in value.message
        assert not seen[0].previous_sources and not seen[0].previous_file_offer
        source['available']=False
        value=await router.route(RouteRequest(text='需要',previous_sources=[source],previous_file_offer=True))
        assert '没有可确认' in value.message and '查看或下载' not in value.message
    asyncio.run(run())


def test_router_unavailable_on_clarifies_without_executing_runner(monkeypatch):
    monkeypatch.setattr(host,'settings',lambda:{'mode':'on','version':'test'})
    async def unavailable(payload):raise TimeoutError()
    monkeypatch.setattr(host,'classify',unavailable)
    async def run():
        started=[]
        async def results():started.append(True);yield 'should not run'
        value=[v async for v in host.route_results(results(),query(),lambda **x:NS(**x))]
        assert not started and value[0].is_final and '稍后重试' in value[0].content
    asyncio.run(run())


def query(**update):
    value=dict(query_id='q',workspace_uuid='w',bot_uuid=host.BOT,pipeline_uuid=host.PIPELINE,
        launcher_type='person',launcher_id='person1',sender_id='staff1',message_chain=[],user_message=NS(content='你好'),
        session=NS(using_conversation=NS(uuid='conversation1')),pipeline_config={'original':True})
    return NS(**(value|update))


def test_host_permissions_intersect_and_do_not_mutate_original():
    resources={'tools':[{'tool_name':'design_search'}],'skills':[{'skill_name':'design-rag'}],
        'knowledge_bases':[{'kb_id':host.KB},{'kb_id':'design'}],'storage':{'workspace_storage':True}}
    before=deepcopy(resources)
    daily=host.filter_resources(resources,'daily')
    assert not daily['tools'] and not daily['skills'] and not daily['knowledge_bases']
    work=host.filter_resources(resources,'knowledge')
    assert work['knowledge_bases']==[{'kb_id':host.KB}] and not work['skills'] and not work['tools']
    assert host.filter_resources({'knowledge_bases':[]},'knowledge')['knowledge_bases']==[]
    assert resources==before


def test_host_scope_not_query_variables_controls_resource_snapshot():
    class Builder:
        async def build_resources_from_binding(self,*args):return {'knowledge_bases':[{'kb_id':host.KB},{'kb_id':'design'}],'skills':['design'],'tools':['bad']}
    host.install_resource_builder(Builder)
    async def run():
        event=NS(event_id='event',workspace_id='w',bot_id=host.BOT)
        binding=NS(processor_id=host.PIPELINE,runner_id=host.RUNNER)
        scope=host.Scope('q','w',host.BOT,'daily',False,'event');token=host.ACTIVE.set(scope)
        try:
            assert not (await Builder().build_resources_from_binding(None,event,binding,None))['knowledge_bases']
            event.workspace_id='other'
            assert (await Builder().build_resources_from_binding(None,event,binding,None))['knowledge_bases']
        finally:host.ACTIVE.reset(token)
        assert (await Builder().build_resources_from_binding(None,event,binding,None))['knowledge_bases']
    asyncio.run(run())


def test_shadow_never_waits_or_changes_answer_and_on_shortcut_keeps_card(monkeypatch):
    cfg={'mode':'shadow','version':'test'};monkeypatch.setattr(host,'settings',lambda:cfg)
    async def classify(payload):
        await asyncio.sleep(.1)
        return {'mode':'on','intent':'clarify','message':'请补充问题','config_version':'test','method':'context'}
    monkeypatch.setattr(host,'classify',classify)
    async def run():
        seen=[]
        async def stream():seen.append('runner');yield NS(all_content='真实回答',is_final=True)
        started=time.monotonic()
        value=[r async for r in host.route_results(stream(),query(),lambda **x:NS(**x))]
        assert value[0].all_content=='真实回答' and time.monotonic()-started<.08 and seen==['runner']
        cfg['mode']='on';seen.clear()
        value=[r async for r in host.route_results(stream(),query(query_id='other'),lambda **x:NS(**x))]
        assert value[0].is_final and value[0].content=='请补充问题' and not seen
        assert host.ACTIVE.get() is None
        await asyncio.gather(*list(host.SHADOW_TASKS))
    asyncio.run(run())


def test_sources_only_from_host_evidence_and_reset_clears_them():
    host.MEMORY.clear();q=query()
    metadata={'result_type':'source_evidence','entry_id':'00000000-0000-4000-8000-000000000001','title':'真实资料',
        'source_file':{'available':True,'kind':'extracted_markdown'},'steps':[{'evidence_ids':['evidence1']}]}
    host.retain(q,'问题','依据真实资料 [evidence1]，需要源文件吗？',[{'id':'p','metadata':metadata}])
    prior=host.previous(q)
    assert prior['offer'] and prior['sources'][0]['kind']=='extracted_markdown'
    host.retain(q,'别的问题','模型伪造了其他来源',[])
    assert not host.previous(q)['sources']
    host.retain(q,'问题','真实资料，需要源文件吗？',[{'id':'p','metadata':metadata}])
    q.session.using_conversation=None
    assert not host.previous(q)['sources']


def test_sample_counts_families_and_required_boundary_cases():
    spec=importlib.util.spec_from_file_location('calibrate',ROOT/'scripts/calibrate-knowledge-intent.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    groups=module.audit();rows=groups['acceptance']
    assert next(r for r in rows if r['text']=='你好，补卡怎么申请')['intent']=='knowledge'
    assert next(r for r in rows if r['text']=='发我报销模板')['intent']=='source_file'
