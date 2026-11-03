import asyncio
import json
import math
from pathlib import Path
import sys

import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
from app.manuals.intent import engine
from app.manuals.intent.supervised import LABEL_MAP,accept,decode,guarded_accept,model_text,verify_manifest
from app.manuals.intent.types import RouteRequest

def scores(scope='company',output='text',clarification='answer',certainty=.98):
 result={}
 for axis,selected in [('scope',scope),('output',output),('clarification',clarification)]:
  labels=LABEL_MAP[axis];result[axis]={k:certainty if k==selected else (1-certainty)/(len(labels)-1) for k in labels}
 return result

GATES={label:{'confidence':.9,'margin':.5} for label in ('daily','knowledge','images','source_file','clarify')}

@pytest.mark.parametrize('scope,output,clarification,intent',[
 ('general','text','answer','daily'),('company','text','answer','knowledge'),
 ('company','images','answer','images'),('company','source_file','answer','source_file'),
 ('unknown','unknown','clarify','clarify')])
def test_explicit_supervised_head_mapping(scope,output,clarification,intent):
 axes,reason=accept(scores(scope,output,clarification),GATES)
 assert axes.intent==intent and not reason

@pytest.mark.parametrize('bad',[float('nan'),float('inf'),-.1,1.1,True,'0.5'])
def test_classifier_invalid_scores_cannot_authorize(bad):
 value=scores();value['scope']['company']=bad
 with pytest.raises(ValueError):decode(value)

def test_truncation_and_inconsistent_factors_abstain():
 assert accept({'truncated':True},GATES)==(None,'classifier_input_truncated')
 assert accept(scores('general','images'),GATES)[0] is None
 assert accept(scores(certainty=.6),GATES)[0] is None

def test_explicit_company_wins_over_generic_adverb():
 result,why=guarded_accept(scores('general'),GATES,RouteRequest(text='我们公司一般怎么申请补贴'))
 assert result is None and why=='classifier_company_scope_conflict'
 result,why=guarded_accept(scores('general'),GATES,RouteRequest(text='帮我润色这句话：公司同事请及时提交资料'))
 assert result.intent=='daily' and not why

def test_missing_source_metadata_is_not_invented():
 text=model_text(RouteRequest(text='下载文件'))
 assert '来源数量' not in text and 'company' not in text
 value=model_text(RouteRequest(text='需要',previous_file_offer=True))
 assert '来源数量：0' in value

def test_business_terms_and_requested_media_cannot_be_silently_general_text():
 for text in ('你好补卡怎么申请','这个月工资什么时候发','报销需要哪些资料'):
  assert guarded_accept(scores('general'),GATES,RouteRequest(text=text))[0] is None
 assert guarded_accept(scores('company','text'),GATES,RouteRequest(text='展示内部培训照片'))[0] is None
 assert guarded_accept(scores('company','text'),GATES,RouteRequest(text='请提供报销表格文件'))[0] is None

def test_supervised_failure_keeps_terra_fallback(monkeypatch):
 cfg={'mode':'shadow','version':'test-v3','terra_enabled':True,'model_path':'fake','sample_set':'v3'}
 artifact={'schema':'factors-v3','supervised_validated':True,'supervised':GATES,
  'bm25_axes':{},'fingerprint':{'index.jsonl':'x','intent-policy.v2.json':'y'}}
 monkeypatch.setattr(engine,'config',lambda:cfg)
 monkeypatch.setattr(engine,'calibration_valid',lambda cfg:artifact)
 class Worker:
  ready=True
  def classify(self,payload,timeout):raise TimeoutError('offline')
 class Terra:
  calls=0
  async def classify(self,request):
   self.calls+=1
   return engine.Axes(knowledge_scope='company',output_kind='text',needs_clarification=False)
 async def run():
  router=engine.Router();router.worker=Worker();router.model_path='fake';router.terra=Terra()
  async def warm():pass
  router.warm=warm
  result=await router.route(RouteRequest(text='本公司福利体检有哪些项目'))
  assert result.mode=='shadow' and result.method=='terra' and result.intent=='knowledge'
  assert router.terra.calls==1 and 'TimeoutError' in result.reason
 asyncio.run(run())

def test_schema_gate_not_just_model_files(monkeypatch,tmp_path):
 from app.manuals.intent import supervised
 monkeypatch.setattr(supervised,'DATA',tmp_path)
 folder=tmp_path/'models/intent/model';folder.mkdir(parents=True)
 (folder/'intent-manifest.json').write_text(json.dumps({'schema':'wrong'}),encoding='utf-8')
 with pytest.raises(ValueError,match='labels'):verify_manifest(folder)

def test_training_reads_only_train_and_development():
 text=(ROOT/'scripts/train-knowledge-intent-v3.py').read_text(encoding='utf-8')
 assert "for name in ('train','development')" in text
 assert "load_rows('acceptance'" not in text and "load_rows('calibration'" not in text

def test_quality_report_alone_cannot_activate_without_human_review(monkeypatch,tmp_path):
 from app.manuals.intent import settings
 monkeypatch.setattr(settings,'report_dir',lambda cfg:tmp_path)
 monkeypatch.setattr(settings,'fingerprint',lambda *args:{'frozen':'yes'})
 cfg={'model_path':'fake','sample_set':'v3'}
 report={'passed':True,'integration_passed':True,'shadow_passed':True,'fingerprint':{'frozen':'yes'},'human_review':'pending'}
 (tmp_path/'acceptance.json').write_text(json.dumps(report),encoding='utf-8')
 assert not settings.activation_valid(cfg)
 report['human_review']='complete'
 (tmp_path/'acceptance.json').write_text(json.dumps(report),encoding='utf-8')
 assert settings.activation_valid(cfg)
 report['fingerprint']={'changed':'yes'}
 (tmp_path/'acceptance.json').write_text(json.dumps(report),encoding='utf-8')
 assert not settings.activation_valid(cfg)
