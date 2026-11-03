"""Calibration-only thresholds, then immutable topic-held-out evaluation.

Old acceptance sets are separately named regression. No test-driven refitting.
Synthetic topic separation is not proof of real employee-language accuracy.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
from dotenv import load_dotenv
load_dotenv(ROOT/'instances/manuals/.env',override=True)
from app.manuals.intent.settings import DATA,SAMPLES,digest,fingerprint,load_rows
from app.manuals.intent.engine import direct,file_followup
from app.manuals.intent.factors import FactorBM25,inspect_request
from app.manuals.intent.supervised import load_network,model_text,infer,decode,guarded_accept,verify_manifest
from app.manuals.intent.types import RouteRequest,axes_for_intent
OUT=DATA/'intent/v3';DELIVERY=ROOT/'output/intent-routing-v3';MODEL=DATA/'models/intent/supervised-bert-v3'
spec=importlib.util.spec_from_file_location('cal_v2',ROOT/'scripts/calibrate-knowledge-intent-v2.py')
v2=importlib.util.module_from_spec(spec);spec.loader.exec_module(v2)

def request(row):
 req=RouteRequest.model_validate({k:v for k,v in row.items() if k in RouteRequest.model_fields})
 if not file_followup(req.text):req=req.model_copy(update={'previous_sources':[],'previous_file_offer':False})
 return req

def preflight(req):
 value=direct(req)
 if value:return value
 signal=inspect_request(req)
 return ('clarify',signal.clarification) if signal.clarification else None

def audit(include_acceptance=False):
 names=['train','development','calibration']+(['acceptance'] if include_acceptance else [])
 sets={n:load_rows(n,'v3') for n in names}
 overlap=[];duplicates=[]
 def norm(r):
  value=request(r).model_dump(mode='json');value['text']=re.sub(r'[\s，,。！？!?；;：:]+','',value['text']).casefold()
  return json.dumps(value,sort_keys=True,ensure_ascii=False)
 for i,a in enumerate(names):
  for b in names[i+1:]:
   overlap.extend(sorted({r['family'] for r in sets[a]} & {r['family'] for r in sets[b]}))
   duplicates.extend(sorted({norm(r) for r in sets[a]} & {norm(r) for r in sets[b]}))
 assert not overlap,'Topic families crossed splits'
 # Reused generic clarification phrases are disclosed and excluded from fresh
 # test claims, not silently relabelled as independent natural-language data.
 assert not duplicates,'Exact contextual requests crossed splits'
 return {'counts':{k:len(v) for k,v in sets.items()},'family_id_overlap':0,'exact_context_duplicates':0,
  'source':'curated_synthetic_scenario','human_review':'pending',
  'known_development_overlap':'Legacy training includes visitor registration; development also includes visitor registration. Development is checkpoint selection only, not an independent accuracy claim.',
  'limitation':'Shared question templates; family IDs and exact contexts audited, semantic paraphrase separation requires human review. Synthetic exercise, not a human-reviewed independent employee corpus.'}

def setup():
 import torch
 torch.set_num_threads(2);torch.set_num_interop_threads(1)
 return load_network(MODEL)

def predictions(rows,net):
 model,tokenizer,manifest=net;result=[]
 for i,row in enumerate(rows):
  req=request(row);started=time.perf_counter()
  scores=infer(model,tokenizer,model_text(req),manifest['max_length'])
  result.append({'id':row['id'],'scores':scores,'elapsed_ms':round(1000*(time.perf_counter()-started),3)})
  if i%40==0:print(json.dumps({'inference_completed':i,'total':len(rows)}),flush=True)
 return result

def fit_bert(rows,scores):
 gates={}
 for label in ('daily','knowledge','images','source_file','clarify'):
  candidates=[]
  for row,pred in zip(rows,scores):
   if pred['scores'].get('truncated'):continue
   axes,confidence,margin=decode(pred['scores'])
   if axes and axes.intent==label:
    eligible,_=guarded_accept(pred['scores'],{label:{'confidence':0,'margin':0}},request(row))
    if eligible:candidates.append((row,pred,confidence,margin))
  best=None
  for confidence in sorted({.5,.7,.8,.9,.95,.98,.99}|{c for _,_,c,_ in candidates}):
   for margin in sorted({0,.1,.3,.5,.8}|{m for _,_,_,m in candidates}):
    gate={'confidence':confidence,'margin':margin}
    selected=[row for row,pred,c,m in candidates if c>=confidence and m>=margin]
    if len(selected)<4 or any(r['intent']!=label for r in selected):continue
    choice=(len(selected),confidence,margin)
    if best is None or choice>best[0]:best=(choice,gate)
  if best:gates[label]={**best[1],'calibration_accepted':best[0][0]}
 return gates

def write(name,value):
 for target in (OUT,DELIVERY):
  target.mkdir(parents=True,exist_ok=True);(target/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def calibrate():
 if (OUT/'acceptance.json').exists() or (OUT/'calibration.json').exists():raise RuntimeError('V3 gates already frozen; create a new version instead of refitting')
 audit_report=audit();verify_manifest(MODEL);stamp=fingerprint(MODEL,'v3');rows=load_rows('calibration','v3');index=FactorBM25(load_rows('index','v3'))
 raw=[]
 for row in rows:
  req=request(row);features=index.features(req);guards=index.guard(features)
  raw.append({'id':row['id'],'expected':{k:row[k] for k in ('knowledge_scope','output_kind','needs_clarification')},
   **v2.compact(features),'blocked':bool([r for r in guards if r!='employee_image_not_read']) or preflight(req) is not None})
 bm25={axis:v2.fit_axis(raw,axis) for axis in ('scope','output')}
 net=setup();scores=predictions(rows,net);bert=fit_bert(rows,scores)
 artifact={'schema':'factors-v3','version':'intent-v3-supervised','fingerprint':stamp,'bm25_axes':bm25,'supervised':bert,
  'supervised_validated':bool(bert),'nli_axes_validated':False,'fitted_at':datetime.now(timezone.utc).isoformat(),
  'fit_data':'v3_calibration_only','model_selection':'train/development only','audit':audit_report,
  'human_review':'pending','calibration_scores':scores,'raw_bm25':raw}
 write('calibration.json',artifact)
 print(json.dumps({'sealed':True,'bm25_axes':bm25,'supervised':bert,'calibration_sha256':digest(OUT/'calibration.json')},ensure_ascii=False),flush=True)

def p95(values):return sorted(values)[max(0,math.ceil(len(values)*.95)-1)] if values else None

def evaluate_rows(rows,index,artifact,net):
 cases=[]
 for i,row in enumerate(rows):
  req=request(row);started=time.perf_counter();metadata=preflight(req);axes=None;layer='unresolved';reason='';reasons=[]
  if metadata:axes=axes_for_intent(metadata[0]);layer='context'
  else:
   axes,_,reasons=index.decide(req,artifact['bm25_axes'])
   if axes:layer='bm25_axes'
   elif net is not None:
    scores=infer(net[0],net[1],model_text(req),net[2]['max_length'])
    axes,reason=guarded_accept(scores,artifact['supervised'],req)
    if axes:layer='bert_supervised'
  pred=axes.intent if axes else None
  cases.append({'id':row['id'],'expected':row['intent'],'expected_scope':row.get('knowledge_scope','general' if row['intent']=='daily' else 'company'),
   'prediction':pred,'correct':pred==row['intent'],'layer':layer,'reason':reason,'guards':reasons,'tags':row['tags'],
   'elapsed_ms':round(1000*(time.perf_counter()-started),3)})
  if i%40==0:print(json.dumps({'evaluated':i,'total':len(rows)}),flush=True)
 automatic=[r for r in cases if r['layer'] in ('bm25_axes','bert_supervised')];clear=[r for r in cases if 'clear' in r['tags']]
 precision=sum(r['correct'] for r in automatic)/len(automatic) if automatic else 0
 coverage=sum(r['layer'] in ('bm25_axes','bert_supervised') for r in clear)/len(clear) if clear else 0
 company_daily=sum(r['expected_scope']=='company' and r['prediction']=='daily' for r in cases)
 latency=p95([r['elapsed_ms'] for r in cases])
 return {'local_auto_count':len(automatic),'local_auto_correct':sum(r['correct'] for r in automatic),'local_auto_precision':precision,
  'clear_count':len(clear),'clear_local_auto_coverage':coverage,'company_to_daily':company_daily,'warm_local_p95_ms':latency,
  'layers':dict(Counter(r['layer'] for r in cases)),'quality_passed':precision>=.95 and coverage>=.6 and company_daily==0,
  'unresolved_are_not_counted_as_correct':True,'terra_not_in_offline_precision':True,'cases':cases}

def evaluate():
 if (OUT/'acceptance.json').exists():raise RuntimeError('Held-out evaluation already sealed; do not refit or overwrite')
 artifact=json.loads((OUT/'calibration.json').read_text(encoding='utf-8'));stamp=fingerprint(MODEL,'v3')
 assert artifact['fingerprint']==stamp,'Source/data changed after threshold freeze'
 audit_report=audit(True);net=setup();index=FactorBM25(load_rows('index','v3'))
 infer(net[0],net[1],'请讲解本公司的内部办理流程',net[2]['max_length'])
 report=evaluate_rows(load_rows('acceptance','v3'),index,artifact,net)
 report.update(fingerprint=stamp,calibration_sha256=digest(OUT/'calibration.json'),dataset_role='fresh_synthetic_topic_holdout_shared_templates',
  passed=report['quality_passed'] and report['warm_local_p95_ms']<=1000,integration_passed=False,shadow_passed=False,human_review='pending',audit=audit_report)
 # Compare on the same new holdout; do not compare percentages from different
 # sets as if they were measured improvement. Both frozen baselines are read-only.
 baseline=json.loads((ROOT/'output/intent-routing-v2/calibration.json').read_text(encoding='utf-8'))
 old=evaluate_rows(load_rows('acceptance','v3'),FactorBM25(load_rows('index','v2')),baseline,None)
 old['dataset_role']='frozen_v2_on_same_v3_topic_holdout'
 write('baseline-v2-same-holdout.json',old)
 ablation=evaluate_rows(load_rows('acceptance','v3'),index,artifact,None)
 ablation['dataset_role']='v3_bm25_without_bert_same_holdout'
 write('ablation-bm25.json',ablation)
 regressions={}
 for version in ('v1','v2'):
  regression=evaluate_rows(load_rows('acceptance',version),index,artifact,net);regression['dataset_role']='known_'+version+'_regression_not_independent'
  write('regression-'+version+'.json',regression)
  regressions[version]={'company_to_daily':regression['company_to_daily'],'local_auto_precision':regression['local_auto_precision']}
 report['known_regression_checks']=regressions
 report['passed']=report['passed'] and all(r['company_to_daily']==0 and r['local_auto_precision']>=.95 for r in regressions.values())
 write('acceptance.json',report)
 print(json.dumps({k:v for k,v in report.items() if k not in ('cases','fingerprint')},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['audit','calibrate','evaluate']);args=parser.parse_args()
 if args.action=='audit':print(json.dumps(audit(),ensure_ascii=False))
 elif args.action=='calibrate':calibrate()
 else:evaluate()
