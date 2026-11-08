"""One bounded A2UI capability probe to the previously confirmed private tester."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import hashlib
import json
import subprocess
import sys
from uuid import uuid4
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,DOCKER,client,data
from build_dingtalk_json_card import messages

def probe(retry_after_permission=False,retry_invalid_request=False):
    receipt=RUNTIME/'a2ui-private-access.private.json'
    if receipt.exists():
        old=json.loads(receipt.read_text(encoding='utf-8'))
        if old.get('attempt_started'):
            if not ((retry_after_permission and old.get('http_status')==403) or
                    (retry_invalid_request and old.get('http_status')==400 and old.get('error_code')=='param.invalid')):
                print('Existing probe found; no automatic duplicate send');return old
            receipt.with_suffix('.previous-denied.json').write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
    sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
    from workrag_agent.store import Store
    bot_id='37416bec-870f-4ecc-9ac7-c2ddbc16123d'
    bot=data(client().get('/api/v1/platform/bots/'+bot_id))['bot']
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    with store.connection() as conn:
        rows=conn.execute("SELECT s.identity FROM wa_answers a JOIN wa_sessions s USING(session_key) WHERE a.question=%s AND s.identity->>'bot'=%s",('资料联调开始',bot_id)).fetchall()
    actors={r['identity']['sender'] for r in rows}
    if len(actors)!=1:raise RuntimeError('The authorized private tester cannot be uniquely identified')
    actor=next(iter(actors));sid='workrag-access-'+uuid4().hex
    card=messages()
    for message in card:
        for key in ('createSurface','updateDataModel','updateComponents'):
            if key in message:message[key]['surfaceId']=sid
    card[1]['updateDataModel']['value'].update(status='[AIGenerating]新卡片接入检查中…',answer='这是一条 WorkRAG 新卡片接口测试，仅发送到已确认的本人单聊。')
    checkpoint={'attempt_started':True,'out_track_id':sid,'recipient_sha256':hashlib.sha256(actor.encode()).hexdigest(),'delivery_verified':False}
    receipt.write_text(json.dumps(checkpoint,indent=2),encoding='utf-8')
    payload={'config':bot['adapter_config'],'actor':actor,'sid':sid,'card':card}
    code=r'''
import asyncio,json,sys,logging
from langbot.libs.dingtalk_api.api import DingTalkClient
logging.disable(logging.CRITICAL)
async def main():
 d=json.load(sys.stdin);cfg=d['config'];bot=DingTalkClient(cfg['client_id'],cfg['client_secret'],'WorkRAG',cfg['client_id'],True,None)
 await bot.get_access_token()
 headers={'x-acs-dingtalk-access-token':bot.access_token}
 body={'outTrackId':d['sid'],'openSpaceId':'dtv1.card//im_robot.'+d['actor'],'protocolVersion':'1.0','userIdType':1,
       'flowStatus':'PROCESSING','a2uiMessages':[json.dumps(m,ensure_ascii=False) for m in d['card']],
       'imRobotOpenSpaceModel':{'supportForward':False},'imRobotOpenDeliverModel':{'robotCode':cfg['client_id']},
       'a2uiAnnotations':[{'surfaceId':d['sid'],'componentId':'answer','type':'artifact'}],'summary':'WorkRAG 新卡片接入测试'}
 async with bot._http_client_context() as c:
  r=await c.post('https://api.dingtalk.com/v1.0/card/ai/instances/createAndDeliver',headers=headers,json=body,timeout=30)
  value=r.json();result={'http_status':r.status_code,'business_success':value.get('success'),
    'error_code':value.get('code') or value.get('errorCode'),'required_scopes':value.get('requiredScopes'),
    'error_message':value.get('message') or value.get('errorMsg')}
  if r.status_code!=200:result['error_details']=value
  deliveries=value.get('result',{}).get('deliverResults',[])
  result['delivery_results']=[{'success':v.get('success'),'space_type':v.get('spaceType')} for v in deliveries]
  if r.status_code==200 and value.get('success') is True:
   update={'outTrackId':d['sid'],'outUpdateId':d['sid']+'-finish','flowStatus':'FINISH',
    'a2uiMessages':[json.dumps({'version':'v1.0','updateDataModel':{'surfaceId':d['sid'],'path':'/status','value':'新卡片接口已接通，等待客户端确认'}})]}
   u=await c.put('https://api.dingtalk.com/v1.0/card/ai/instances/update',headers=headers,json=update,timeout=30)
   result['finish_http_status']=u.status_code;result['finish_business_success']=u.json().get('success')
  print(json.dumps(result))
asyncio.run(main())
'''
    run=subprocess.run([DOCKER,'exec','-i','-e','PYTHONPATH=/app/src','workrag-langbot-1','/app/.venv/bin/python','-c',code],
                       input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=100)
    if run.returncode:raise RuntimeError('A2UI probe outcome unknown; inspect privately before retrying')
    result={**checkpoint,**json.loads(run.stdout.strip().splitlines()[-1])}
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in {'error_message','error_details'}},ensure_ascii=True))
    return result

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--retry-after-permission',action='store_true')
    parser.add_argument('--retry-invalid-request',action='store_true');args=parser.parse_args()
    probe(args.retry_after_permission,args.retry_invalid_request)
