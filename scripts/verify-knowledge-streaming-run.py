"""One internal Pipeline run; no DingTalk send and never auto-resubmit."""
import importlib.util
import argparse
import json
from pathlib import Path
import time
import subprocess
import httpx

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'data/manuals/runtime/streaming-verification.private.json'
spec=importlib.util.spec_from_file_location('connection',ROOT/'scripts/connect-langbot-knowledge.py')
conn=importlib.util.module_from_spec(spec);spec.loader.exec_module(conn)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--after-repair',action='store_true')
    parser.add_argument('--check-startup',action='store_true')
    parser.add_argument('--after-services',action='store_true')
    args=parser.parse_args()
    with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':conn.credential()},timeout=75) as client:
        if PRIVATE.exists():
            saved=json.loads(PRIVATE.read_text(encoding='utf-8'))
            if saved.get('status')=='submitted' and args.check_startup:
                started=subprocess.check_output(['docker','inspect','--format','{{.State.StartedAt}}','langbot'],text=True).strip()
                logs=subprocess.run(['docker','logs','--since',started,'langbot'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
                log=logs.stdout+logs.stderr
                if 'Processing request from' in log or f'/pipelines/{conn.PIPELINE}/run' in log:
                    raise RuntimeError('A request may have reached Host. Inspect existing run; do not retry.')
                saved['status']='not_received_during_startup'
                saved['proof']='No pipeline requests or scheduled queries since container start; transport closed during startup.'
            if saved.get('status')=='unknown' and saved.get('session_id'):
                data=conn.data(client.get('/api/v1/monitoring/messages',params={'sessionId':saved['session_id'],'limit':8}))
                file=PRIVATE.with_name('streaming-messages.private.json')
                file.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps({'followed_original_session':True,'saved_private':True}))
                return
            service_check = args.after_services and saved.get('status')=='completed' and '无法' in saved.get('reply','')
            if (args.after_repair and saved.get('status') in ('failed','not_received_during_startup')) or service_check:
                PRIVATE.with_name('streaming-verification-before-repair.private.json').write_text(
                    json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
            else:
                print(json.dumps({'already_submitted':True,'status':saved.get('status')}))
                return
        start=time.monotonic()
        # Verify HTTP startup completed before marking a run submitted.
        conn.data(client.get(f'/api/v1/pipelines/{conn.PIPELINE}'))
        PRIVATE.write_text(json.dumps({'status':'submitted'}),encoding='utf-8')
        result=conn.data(client.post(f'/api/v1/pipelines/{conn.PIPELINE}/run',json={
            'message':('请检索《LSD新员工入职培训》，说明补卡申请的次数限制和申请时限，并引用资料页码。'
                if args.after_services else '根据《LSD新员工入职培训》，每月允许补卡几次、申请时限是多少？请给出依据。')}))
        result['elapsed_seconds']=round(time.monotonic()-start,2)
        PRIVATE.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        answer=result.get('reply','')
        print(json.dumps({'status':result.get('status'),'elapsed_seconds':result['elapsed_seconds'],
            'query_id':result.get('query_id'),'has_answer':bool(answer),'has_onboarding_source':'LSD新员工入职培训' in answer,
            'has_page':'6' in answer,'platform':'internal_websocket_only'}))


if __name__=='__main__': main()
