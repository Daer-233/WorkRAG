"""Calibrate factors on V2 calibration only, seal thresholds, then evaluate.

No BERT training, weight changes or new NLI gates in this phase. Old NLI
performance/accuracy evidence remains valid history, not a factor calibration.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
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
from app.manuals.intent.engine import direct,file_followup
from app.manuals.intent.factors import FactorBM25,inspect_request,passes,policy
from app.manuals.intent.settings import MODEL,SAMPLES,digest,fingerprint,load_rows
from app.manuals.intent.types import Axes,RouteRequest,axes_for_intent

OUT=ROOT/'data/manuals/intent/v2'
DELIVERY=ROOT/'output/intent-routing-v2'


def request(row):return RouteRequest.model_validate({k:v for k,v in row.items() if k in RouteRequest.model_fields})


def audit():
    sets={name:load_rows(name,version='v2') for name in ('index','calibration','acceptance')}
    for name,rows in sets.items():
        assert len(rows)=={'index':120,'calibration':120,'acceptance':100}[name]
        assert len({r['id'] for r in rows})==len(rows)
        for row in rows:
            assert row['family'] and row['source_type']=='curated_synthetic_scenario'
            assert row['reviewed_by']=='agent' and row['human_review']=='pending'
            expected=Axes(knowledge_scope=row['knowledge_scope'],output_kind=row['output_kind'],needs_clarification=row['needs_clarification'])
            assert expected.intent==row['intent']
            request(row)
    def normalized(row):
        req=request(row).model_dump(mode='json')
        req['text']=re.sub(r'[\s，,。！？!?；;：:]+','',req['text']).casefold()
        return json.dumps(req,sort_keys=True,ensure_ascii=False)
    for a,b in (('index','calibration'),('index','acceptance'),('calibration','acceptance')):
        assert not {r['family'] for r in sets[a]} & {r['family'] for r in sets[b]},'Request family crossed splits'
        assert not {normalized(r) for r in sets[a]} & {normalized(r) for r in sets[b]},'Duplicate request/context crossed splits'
    known=load_rows('acceptance',version='v1')
    # Identical old short follow-ups are regression, never a "new" acceptance.
    assert not {re.sub(r'\s+','',r['text']) for r in known} & {re.sub(r'\s+','',r['text']) for r in sets['acceptance']},'Known V1 text reused in fresh test'
    boundary=sum(any(t in row['tags'] for t in ('boundary','mixed','multi_turn')) for row in sets['acceptance'])
    assert boundary>=30
    return sets,{'counts':{k:len(v) for k,v in sets.items()},'fresh_boundary_count':boundary,
        'cross_split_exact_duplicates':0,'cross_split_family_overlap':0,'v1_acceptance_text_reused':0,'human_review':'pending'}


def compact(features):
    return {axis:features[axis] for axis in ('scope','output')}


def quantiles(values):
    ordered=sorted(set(values))
    if len(ordered)<=14:return ordered
    return sorted({ordered[round(i*(len(ordered)-1)/13)] for i in range(14)})


def fit_axis(rows,axis):
    gates={};minimum=policy()['minimum_calibration_accepts']
    labels=('general','company') if axis=='scope' else ('text','images','source_file')
    for label in labels:
        candidates=[r for r in rows if not r['blocked'] and r[axis]['label']==label]
        best=None
        floor=policy()['daily_min_coverage'] if axis=='scope' and label=='general' else policy()['company_min_coverage'] if axis=='scope' else policy()['action_min_coverage']
        for score in quantiles(r[axis]['score'] for r in candidates):
            for margin in quantiles(r[axis]['margin'] for r in candidates):
                for coverage in sorted({floor,.2,.35,.5,.65,.8}):
                    if coverage<floor:continue
                    for support in (0.15,0.3,0.5):
                        gate={'score':score,'margin':margin,'coverage':coverage,'support':support}
                        selected=[r for r in candidates if passes(r[axis],{label:gate})]
                        if len(selected)<minimum:continue
                        field='knowledge_scope' if axis=='scope' else 'output_kind'
                        if any(r['expected'][field]!=label or r['expected']['needs_clarification'] for r in selected):continue
                        # Same coverage -> prefer stricter measured boundaries.
                        choice=(len(selected),score,margin,coverage,support)
                        if best is None or choice>best[0]:best=(choice,gate)
        if best:gates[label]={**best[1],'calibration_accepted':best[0][0]}
    return gates


def preflight(req):
    metadata=direct(req)
    if metadata:return metadata
    signal=inspect_request(req)
    if signal.clarification:return 'clarify',signal.clarification
    return None


def calibrate(sets):
    OUT.mkdir(parents=True,exist_ok=True);stamp=fingerprint(MODEL)
    # Once this held-out set has been evaluated, fitting new thresholds against
    # it is prohibited. Data/profile must be versioned for a new iteration.
    if (OUT/'acceptance.json').exists():
        old=json.loads((OUT/'acceptance.json').read_text(encoding='utf-8'))
        if old['fingerprint']['acceptance.jsonl']==stamp['acceptance.jsonl']:
            raise RuntimeError('This held-out set is already opened; do not refit against the same test. Create the next version.')
    model=FactorBM25(sets['index']);rows=[]
    for row in sets['calibration']:
        req=request(row);features=model.features(req);guard=model.guard(features)
        rows.append({'id':row['id'],'expected':{k:row[k] for k in ('knowledge_scope','output_kind','needs_clarification')},
            **compact(features),'blocked':bool([r for r in guard if r!='employee_image_not_read']) or preflight(req) is not None,'guards':guard})
    gates={axis:fit_axis(rows,axis) for axis in ('scope','output')}
    artifact={'schema':'factors-v2','version':'intent-v2-factors','fingerprint':stamp,
        'fitted_at':datetime.now(timezone.utc).isoformat(),'bm25_axes':gates,'nli':{},'nli_axes_validated':False,
        'nli_reason':'V1 flat NLI gates and latency did not validate the new factors; no retraining or optimization in phase 1-3',
        'fit_data':'calibration_only','minimum_calibration_accepts':policy()['minimum_calibration_accepts'],
        'human_review':'pending','raw_features':rows}
    replay=evaluate_rows(sets['calibration'],model,artifact)
    artifact['calibration_replay']={k:v for k,v in replay.items() if k!='cases'}
    text=json.dumps(artifact,ensure_ascii=False,indent=2)
    (OUT/'calibration.json').write_text(text,encoding='utf-8')
    print(json.dumps({'calibrated':True,'gates':gates,'calibration_replay':artifact['calibration_replay'],'calibration_sha256':digest(OUT/'calibration.json')},ensure_ascii=False,indent=2))


def p95(values):return sorted(values)[max(0,math.ceil(len(values)*.95)-1)] if values else None


def evaluate_rows(rows,model,artifact):
    cases=[]
    # Include feature extraction, all abstention checks and model construction
    # warm-up separately; measure the actual local decision path per request.
    model.features(request(rows[0]))
    for row in rows:
        req=request(row);started=time.perf_counter();metadata=preflight(req)
        axes=None;method='unresolved';reasons=[];features={}
        if metadata:axes=axes_for_intent(metadata[0]);method='context';reasons=[metadata[1]]
        else:
            axes,raw,reasons=model.decide(req,artifact['bm25_axes']);features=compact(raw)
            if axes:method='bm25_axes'
        pred=axes.intent if axes else None
        cases.append({'id':row['id'],'expected':row['intent'],'expected_scope':row.get('knowledge_scope','general' if row['intent']=='daily' else 'company'),
            'prediction':pred,'axes':axes.model_dump() if axes else None,'layer':method,'correct':pred==row['intent'],
            'guards':reasons,'features':features,'elapsed_ms':round(1000*(time.perf_counter()-started),3),'tags':row['tags']})
    automatic=[r for r in cases if r['layer']=='bm25_axes'];clear=[r for r in cases if 'clear' in r['tags']]
    company_daily=sum(r['expected_scope']=='company' and r['prediction']=='daily' for r in cases)
    precision=sum(r['correct'] for r in automatic)/len(automatic) if automatic else 0
    coverage=sum(r['layer']=='bm25_axes' for r in clear)/len(clear) if clear else 0
    latency=p95([r['elapsed_ms'] for r in cases])
    return {'local_auto_precision':precision,'clear_local_auto_coverage':coverage,'company_to_daily':company_daily,
        'local_auto_count':len(automatic),'local_auto_correct':sum(r['correct'] for r in automatic),'clear_count':len(clear),
        'warm_local_p95_ms':latency,'layers':dict(Counter(r['layer'] for r in cases)),
        'unresolved_are_not_counted_as_correct':True,'terra_not_in_offline_precision':True,'cases':cases,
        'quality_passed':precision>=.95 and coverage>=.6 and company_daily==0}


def evaluate(sets,audit_report):
    artifact=json.loads((OUT/'calibration.json').read_text(encoding='utf-8'));stamp=fingerprint(MODEL)
    assert artifact['fingerprint']==stamp,'Frozen calibration no longer matches code or data'
    frozen=digest(OUT/'calibration.json');model=FactorBM25(sets['index'])
    report=evaluate_rows(sets['acceptance'],model,artifact)
    report.update(fingerprint=stamp,calibration_sha256=frozen,dataset_role=artifact.get('evaluation_role','fresh_independent_v2_acceptance'),
        passed=report['quality_passed'] and report['warm_local_p95_ms']<=1000,
        integration_passed=False,shadow_passed=False,human_review='pending',audit=audit_report,
        nli_axes_validated=False,scope='First three improvements only; no new BERT training or speed claim')
    regression_rows=[json.loads(line) for line in (SAMPLES/'v2/regression-v1.jsonl').read_text(encoding='utf-8').splitlines()]
    regression=evaluate_rows(regression_rows,model,artifact)
    regression['dataset_role']='known_v1_regression_not_independent_acceptance'
    for target in (OUT,DELIVERY):
        target.mkdir(parents=True,exist_ok=True)
        (target/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'regression-v1.json').write_text(json.dumps(regression,ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'calibration.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases','fingerprint')},ensure_ascii=False,indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['audit','calibrate','evaluate']);args=p.parse_args()
    sets,audit_report=audit()
    if args.action=='audit':print(json.dumps(audit_report,ensure_ascii=False))
    elif args.action=='calibrate':calibrate(sets)
    else:evaluate(sets,audit_report)


if __name__=='__main__':main()
