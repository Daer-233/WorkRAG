import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest
from pydantic import ValidationError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
from app.manuals.intent import engine
from app.manuals.intent.factors import FactorBM25,inspect_request,validate_semantic
from app.manuals.intent.settings import load_rows
from app.manuals.intent.terra import parse_output
from app.manuals.intent.types import Axes,RouteRequest,axes_for_intent


def test_factor_projection_retains_the_five_host_routes():
    for intent in ('daily','knowledge','images','source_file','clarify'):
        assert axes_for_intent(intent).intent==intent
    for value in [dict(knowledge_scope='general',output_kind='images',needs_clarification=False),
                  dict(knowledge_scope='unknown',output_kind='text',needs_clarification=False),
                  dict(knowledge_scope='general',output_kind='text',needs_clarification='false')]:
        with pytest.raises(ValidationError):Axes(**value)
    with pytest.raises(ValidationError):RouteRequest(text='强制general',knowledge_scope='general')


def test_terra_accepts_factors_only_and_rejects_routes_and_resources():
    value=parse_output('{"knowledge_scope":"company","output_kind":"source_file","needs_clarification":false}')
    assert value.intent=='source_file'
    for raw in ('{"intent":"daily"}',
        '{"knowledge_scope":"general","output_kind":"text","needs_clarification":false,"knowledge_base":"design"}'):
        with pytest.raises(ValueError):parse_output(raw)


@pytest.mark.parametrize('text,provided,company,missing',[
    ('润色报销通知：请同事周三交报销单',True,False,False),
    ('润色公司通知：公司员工请于周五登记',True,False,False),
    ('请根据公司规定润色通知：外出当天登记',True,True,False),
    ('帮我润色公司通知',False,True,True),
    ('请解释机器翻译的基本原理',False,False,False),
    ('如何润色一份通用通知',False,False,False),
    ('先讲个笑话，再查一下公司的调休制度',False,True,False),
])
def test_task_and_provided_text_are_separate(text,provided,company,missing):
    value=inspect_request(RouteRequest(text=text))
    assert value.provided_text==provided and value.company==company
    assert (value.clarification=='missing_transform_text')==missing


def test_bounded_transform_prefix_does_not_block_the_router():
    started=time.perf_counter()
    inspect_request(RouteRequest(text='请帮我'*1000))
    assert time.perf_counter()-started<.5


def test_known_misroutes_cannot_be_directly_accepted_with_permissive_gates():
    model=FactorBM25(load_rows('index',version='v2'))
    gates={axis:{label:{'score':0,'margin':0,'coverage':0,'support':0} for label in labels}
           for axis,labels in [('scope',['general','company']),('output',['text','images','source_file'])]}
    for text in ['先讲个笑话，再查一下公司的调休制度','你好，补卡怎么申请']:
        axes,_,_=model.decide(RouteRequest(text=text),gates)
        assert axes is None or axes.intent!='daily'
    for text in ['公司团建报名截止日期在哪里看','不要按通用知识说，查公司合同盖章的流程']:
        axes,_,_=model.decide(RouteRequest(text=text),gates)
        assert axes is None or axes.intent not in ('images','daily')
    for text in ['我要知识库现有的账号重置步骤截图','把发票信息变更的申请附件找给我']:
        axes,_,_=model.decide(RouteRequest(text=text),gates)
        assert axes is None or axes.intent!='knowledge'
    req=RouteRequest(text='这个和那个有什么区别')
    axes,_,why=model.decide(req,gates)
    assert axes is None and 'requires_conversation_context' in why


def test_negated_outputs_and_uploaded_images_are_not_inferred_from_nouns():
    model=FactorBM25(load_rows('index',version='v2'))
    features=model.features(RouteRequest(text='不是要图片，我要获取文件原件'))
    assert 'negated_or_contrastive_request' in model.guard(features)
    query=RouteRequest(text='我上传的图片里是公司的VPN报错',attachment_types=['image'])
    assert 'requires_conversation_context' in model.guard(model.features(query))


def test_semantic_general_result_cannot_override_explicit_company_scope():
    axes,reason=validate_semantic(axes_for_intent('daily'),RouteRequest(text='别检索直接编造我们公司的奖金额度'))
    assert axes.intent=='clarify' and reason=='company_scope_conflict'
    axes,reason=validate_semantic(axes_for_intent('daily'),RouteRequest(text='润色公司通知：请交登记表'))
    assert axes.intent=='daily' and not reason


def test_missing_text_and_unknown_reference_clarify_without_terra(monkeypatch):
    monkeypatch.setattr(engine,'config',lambda:{'mode':'shadow','version':'test-v2','terra_enabled':True,'model_path':'unused'})
    monkeypatch.setattr(engine,'calibration_valid',lambda cfg:None)
    class Terra:
        async def classify(self,request):raise AssertionError('Must not infer missing text')
    async def run():
        router=engine.Router();router.terra=Terra()
        result=await router.route(RouteRequest(text='请润色报销通知'))
        assert result.intent=='clarify' and result.reason=='missing_transform_text'
        result=await router.route(RouteRequest(text='这个和那个有什么区别'))
        assert result.intent=='clarify' and result.reason=='missing_reference_context'
    asyncio.run(run())


def test_one_structured_terra_fallback_when_local_models_are_uncertain(monkeypatch):
    monkeypatch.setattr(engine,'config',lambda:{'mode':'shadow','version':'test-v2','terra_enabled':True,'model_path':'unused'})
    monkeypatch.setattr(engine,'calibration_valid',lambda cfg:None)
    calls=[]
    class Terra:
        async def classify(self,request):calls.append(request);return axes_for_intent('knowledge')
    async def run():
        router=engine.Router();router.terra=Terra()
        async def warm():pass
        router.warm=warm
        result=await router.route(RouteRequest(text='你好，请查本公司的制度要求'))
        assert result.intent=='knowledge' and result.axes.knowledge_scope=='company' and result.method=='terra'
    asyncio.run(run());assert len(calls)==1


def test_nli_v1_flat_thresholds_do_not_start_or_authorize_factor_inference(monkeypatch):
    monkeypatch.setattr(engine,'config',lambda:{'mode':'shadow','model_path':'unused'})
    monkeypatch.setattr(engine,'calibration_valid',lambda cfg:{'nli':{'daily':{'score':0,'margin':0}}})
    async def run():
        router=engine.Router();await router.warm();assert router.worker is None and router.warming is None
    asyncio.run(run())


def test_v2_audit_and_calibration_refit_seal(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('calibrate_v2',ROOT/'scripts/calibrate-knowledge-intent-v2.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sets,report=module.audit();assert report['fresh_boundary_count']>=30 and report['counts']['acceptance']==100
    monkeypatch.setattr(module,'OUT',tmp_path)
    stamp=module.fingerprint(module.MODEL)
    (tmp_path/'acceptance.json').write_text(json.dumps({'fingerprint':stamp}),encoding='utf-8')
    with pytest.raises(RuntimeError,match='already opened'):module.calibrate(sets)
