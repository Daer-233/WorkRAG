"""Local HTTP integration probes; never dispatches DingTalk messages."""
import json
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
from app.manuals.intent.factors import FactorBM25
from app.manuals.intent.supervised import guarded_accept
from app.manuals.intent.types import RouteRequest
import httpx

def main():
 artifact=json.loads((DATA/'intent/v3/calibration.json').read_text(encoding='utf-8'))
 index=FactorBM25(load_rows('index','v3'));cases=[];selected={};unresolved=None
 for row,pred in zip(load_rows('calibration','v3'),artifact['calibration_scores']):
  req=RouteRequest.model_validate({k:v for k,v in row.items() if k in RouteRequest.model_fields})
  axes,_,_=index.decide(req,artifact['bm25_axes'])
  if not axes:axes,_=guarded_accept(pred['scores'],artifact['supervised'],req)
  if axes and axes.intent==row['intent'] and axes.intent not in selected and axes.intent!='clarify':selected[axes.intent]=req
  if not axes and unresolved is None and 'clear' in row['tags']:unresolved=(req,row['intent'])
 with httpx.Client(base_url='http://127.0.0.1:8060',headers={'X-Manual-Request':'1'},timeout=30,trust_env=False) as client:
  status=None
  for attempt in range(100):
   try:status=client.get('/api/v1/manuals/intent/status').raise_for_status().json()
   except httpx.ConnectError:
    time.sleep(2);continue
   if status.get('model_ready'):break
   if attempt%15==0:print(json.dumps({'waiting_for_background_warmup':True,'seconds':attempt*2}),flush=True)
   time.sleep(2)
  assert status['effective_mode']=='shadow' and status['version']=='intent-v3-supervised' and status['model_ready'],status
  assert not status['activation_allowed']
  for expected,req in selected.items():
   started=time.perf_counter();value=client.post('/api/v1/manuals/intent/route',json=req.model_dump(mode='json')).raise_for_status().json()
   cases.append({'expected':expected,'actual':value['intent'],'method':value['method'],'mode':value['mode'],
    'elapsed_ms':value['elapsed_ms'],'http_ms':round(1000*(time.perf_counter()-started),2),'correct':value['intent']==expected})
  value=client.post('/api/v1/manuals/intent/route',json={'text':'','attachment_types':['image']}).raise_for_status().json()
  pure_image=value['intent']=='clarify' and value['reason']=='image_text_missing' and value['has_image']
  spoof=client.post('/api/v1/manuals/intent/route',json={'text':'公司规定','intent':'daily'}).status_code==422
  terra=None
  if unresolved:
   req,expected=unresolved
   value=client.post('/api/v1/manuals/intent/route',json=req.model_dump(mode='json')).raise_for_status().json()
   terra={'expected':expected,'actual':value['intent'],'method':value['method'],'reason':value['reason'],'elapsed_ms':value['elapsed_ms'],
    'safely_completed':value['method'] in ('terra','fallback'),'not_in_local_accuracy':True}
 report={'passed':all(c['correct'] and c['mode']=='shadow' for c in cases) and pure_image and spoof,
  'status':status,'calibration_probe_cases':cases,'pure_image_asks_for_text':pure_image,'employee_cannot_set_route_field':spoof,
  'terra_probe':terra,'dataset_role':'calibration_integration_probes_not_independent_acceptance','employee_messages_sent':0}
 (ROOT/'output/intent-routing-v3/api.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
 if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
