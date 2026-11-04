"""Exercise the actual isolated classifier process; no employee messages."""
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
from app.manuals.intent.settings import DATA,load_rows
from app.manuals.intent.nli import BertWorker
from app.manuals.intent.supervised import worker,decode
from app.manuals.intent.types import RouteRequest

def main():
 service=BertWorker(DATA/'models/intent/supervised-bert-v3',target=worker)
 began=time.perf_counter();assert service.start(),service.error;load_ms=(time.perf_counter()-began)*1000
 latencies=[];mapping=True;timeout=False;truncation=False
 try:
  for row in load_rows('calibration','v3')[:30]:
   request=RouteRequest.model_validate({k:v for k,v in row.items() if k in RouteRequest.model_fields})
   started=time.perf_counter();scores=service.classify(request.model_dump(mode='json'),2)
   latencies.append((time.perf_counter()-started)*1000)
   # Contradictory axes are a valid abstention, not a label-map corruption.
   decoded=decode(scores);mapping=mapping and len(decoded)==3
  scores=service.classify(RouteRequest(text='请说明公司这个流程的详细资料。'*100).model_dump(mode='json'),2)
  truncation=scores.get('truncated') is True
  try:service.classify(RouteRequest(text='公司考勤规则').model_dump(mode='json'),.000001)
  except TimeoutError:timeout=not service.ready and service.process is None
 finally:service.close()
 report={'passed':mapping and truncation and timeout,'model_ready':True,'explicit_label_maps':mapping,
  'overlength_abstains_without_silent_truncation':truncation,'hard_timeout_kills_isolated_worker':timeout,
  'load_ms':round(load_ms,2),'single_request_ms':latencies,
  'warm_worker_p95_ms':round(sorted(latencies)[math.ceil(len(latencies)*.95)-1],2),'employee_messages_sent':0}
 target=ROOT/'output/intent-routing-v3/worker.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False),flush=True)
 if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
