"""Fit thresholds on calibration only, freeze, then evaluate held-out cases."""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
from dotenv import load_dotenv
load_dotenv(ROOT/'instances/manuals/.env',override=True)
from app.manuals.intent.bm25 import BM25,accepted,ranking
from app.manuals.intent.engine import direct
from app.manuals.intent.nli import BertWorker
from app.manuals.intent.settings import config,digest,fingerprint,load_rows
from app.manuals.intent.types import LABELS,RouteRequest,context_text


def request(row):return RouteRequest.model_validate({k:v for k,v in row.items() if k in RouteRequest.model_fields})


def audit():
    groups={name:load_rows(name) for name in ('index','calibration','acceptance')}
    for name,rows in groups.items():
        expected={'index':80,'calibration':60,'acceptance':100}[name]
        assert len(rows)==expected
        assert len({r['id'] for r in rows})==expected
        assert all(r['source_type'] and r['reviewed_by'] for r in rows)
    assert Counter(r['intent'] for r in groups['index'])==dict.fromkeys(LABELS[:4],20)
    for a,b in (('index','calibration'),('index','acceptance'),('calibration','acceptance')):
        assert not {r['family'] for r in groups[a]} & {r['family'] for r in groups[b]}
        # Identical text may only occur with materially different server context.
        def normalized(r):return json.dumps(request(r).model_dump(mode='json'),sort_keys=True,ensure_ascii=False)
        assert not {normalized(r) for r in groups[a]} & {normalized(r) for r in groups[b]},f'duplicate {a}/{b}'
    assert sum(any(t in r['tags'] for t in ('boundary','mixed','multi_turn')) for r in groups['acceptance'])>=30
    return groups


def fit(scored):
    gates={}
    for label in LABELS:
        candidates=[(row,*ranking(row['scores'])[1:]) for row in scored if ranking(row['scores'])[0]==label]
        best=None
        for score in sorted({s for _,s,_ in candidates}):
            for gap in sorted({m for _,_,m in candidates}):
                selected=[r for r,s,m in candidates if s>=score and m>=gap and s>0]
                if len(selected)<3 or any(r['expected']!=label for r in selected):continue
                choice=(len(selected),score,gap)
                if best is None or choice>best:best=choice
        if best:gates[label]={'score':best[1],'margin':best[2],'calibration_accepted':best[0]}
    return gates


def p95(values):return sorted(values)[max(0,math.ceil(.95*len(values))-1)] if values else None


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--audit-only',action='store_true');parser.add_argument('--calibrate',action='store_true')
    parser.add_argument('--diagnostic-nli-timeout',type=float,default=2,help='Offline measurement only; serving hard timeout remains two seconds')
    parser.add_argument('--reuse-scores',action='store_true',help='Reuse only score artifacts with identical data, model and inference code hashes')
    args=parser.parse_args()
    groups=audit()
    if args.audit_only:print('Dataset audit passed: 80/60/100; no exact request or family overlap. Human business review pending.');return
    cfg=config();out=ROOT/'data/manuals/intent';out.mkdir(parents=True,exist_ok=True)
    stamp=fingerprint(cfg['model_path']);bm25=BM25(groups['index']);worker=BertWorker(cfg['model_path'])
    cached={}
    if args.reuse_scores:
        keys=['index.jsonl','calibration.jsonl','acceptance.jsonl','model_manifest','bm25.py','nli.py','types.py']
        for filename,field in [('calibration.json','raw_scores'),('acceptance.json','cases')]:
            old=json.loads((out/filename).read_text(encoding='utf-8'))
            assert all(old['fingerprint'].get(k)==stamp.get(k) for k in keys),'Inference or data changed; cannot reuse scores'
            cached.update({r['id']:r for r in old[field]})
    ready=bool(cached) or worker.start();print('NLI ready:',ready,'cached:',bool(cached),'error:',worker.error,flush=True)
    def score(rows):
        result=[]
        for position,row in enumerate(rows,1):
            if row['id'] in cached:
                result.append({k:v for k,v in cached[row['id']].items() if k in ('id','expected','bm25','nli','failure','bm25_ms','nli_ms','elapsed_ms')});continue
            req=request(row);start=time.monotonic();bs=bm25.scores(req.text);ns={};failure='';bm_ms=1000*(time.monotonic()-start)
            nli_started=time.monotonic()
            if ready:
                try:ns=worker.classify(context_text(req),timeout=args.diagnostic_nli_timeout)
                except Exception as exc:failure=type(exc).__name__
            result.append({'id':row['id'],'expected':row['intent'],'bm25':bs,'nli':ns,'failure':failure,
                'bm25_ms':round(bm_ms,2),'nli_ms':round(1000*(time.monotonic()-nli_started),2),
                'elapsed_ms':round(1000*(time.monotonic()-start),2)})
            if position%10==0:print('Scored',position,'/',len(rows),flush=True)
        return result
    try:
        location=out/'calibration.json'
        if args.calibrate:
            scored=score(groups['calibration'])
            bm=fit([{'scores':r['bm25'],'expected':r['expected']} for r in scored if direct(request(next(x for x in groups['calibration'] if x['id']==r['id']))) is None])
            remainder=[r for r in scored if not accepted(r['bm25'],bm)]
            nli=fit([{'scores':r['nli'],'expected':r['expected']} for r in remainder])
            artifact={'fingerprint':stamp,'bm25':bm,'nli':nli,'model_ready':ready,
                'method':'per-label score and distinct-intent margin; >=3 calibration accepts, zero calibration errors',
                'human_review':'pending','raw_scores':scored}
            location.write_text(json.dumps(artifact,ensure_ascii=False,indent=2),encoding='utf-8')
        artifact=json.loads(location.read_text(encoding='utf-8'));assert artifact['fingerprint']==stamp,'Calibration stale'
        scored=score(groups['acceptance']);cases=[]
        for row,scores in zip(groups['acceptance'],scored):
            metadata=direct(request(row));pred=None;layer='unresolved'
            if metadata:pred=metadata[0];layer='context'
            elif accepted(scores['bm25'],artifact['bm25']):pred=ranking(scores['bm25'])[0];layer='bm25'
            elif scores['nli_ms']<=2000 and accepted(scores['nli'],artifact['nli']):pred=ranking(scores['nli'])[0];layer='bert_nli'
            cases.append({**scores,'prediction':pred,'layer':layer,'correct':pred==row['intent'],'tags':row['tags']})
        automatic=[r for r in cases if r['layer'] in ('bm25','bert_nli')]
        clear=[r for r in cases if 'clear' in r['tags']]
        correct=sum(r['correct'] for r in automatic);precision=correct/len(automatic) if automatic else 0
        coverage=sum(r['layer'] in ('bm25','bert_nli') for r in clear)/len(clear)
        latency=p95([r['elapsed_ms'] for r in cases if not r['failure']]);company_daily=sum(r['expected']=='knowledge' and r['prediction']=='daily' for r in cases)
        passed=precision>=.95 and coverage>=.60 and company_daily==0 and latency is not None and latency<=1000 and all(not r['failure'] for r in cases)
        report={'fingerprint':stamp,'passed':passed,'integration_passed':False,'shadow_passed':False,'human_review':'pending',
            'local_auto_precision':precision,'clear_local_auto_coverage':coverage,'company_to_daily':company_daily,
            'warm_local_probe_p95_ms':latency,'raw_nli_p95_ms':p95([r['nli_ms'] for r in cases if r['nli']]),
            'nli_hard_timeout_violations':sum(r['nli_ms']>2000 for r in cases),
            'latency_measurement':'offline sequential BM25 plus NLI diagnostic probe, not live request latency',
            'diagnostic_nli_timeout_seconds':args.diagnostic_nli_timeout,
            'layers':dict(Counter(r['layer'] for r in cases)),
            'clear_count':len(clear),'automatic_count':len(automatic),'automatic_correct':correct,
            'terra_not_in_offline_precision':True,'cases':cases}
        (out/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in ('cases','fingerprint')},ensure_ascii=False,indent=2))
    finally:worker.close()


if __name__=='__main__':main()
