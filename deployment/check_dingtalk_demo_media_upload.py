"""Upload only synthetic demo bytes; never deliver messages or publish cards."""
import base64
import json
import subprocess
from pathlib import Path
from install_agent import client,data,ROOT,RUNTIME,DOCKER

bot=data(client().get('/api/v1/platform/bots'))['bots'][0]
materials=json.loads((RUNTIME/'demo-materials.json').read_text(encoding='utf-8'))
document=Path(materials['documents'][0]['source_file'])
picture=document.with_name(materials['documents'][0]['marker']+'-step-2.png')
payload={'config':bot['adapter_config'],'files':[
    {'type':'image','name':picture.name,'mime':'image/png','bytes':base64.b64encode(picture.read_bytes()).decode()},
    {'type':'file','name':document.name,'mime':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','bytes':base64.b64encode(document.read_bytes()).decode()}]}
code='''import asyncio,sys,json,base64,logging
logging.disable(logging.CRITICAL)
from langbot.libs.dingtalk_api.api import DingTalkClient
async def run():
 value=json.load(sys.stdin);cfg=value['config'];bot=DingTalkClient(cfg['client_id'],cfg['client_secret'],'WorkRAG demo',cfg['client_id'],True,None)
 result={'messages_sent':False,'template_published':False,'uploads':[]}
 token=await bot.get_legacy_access_token()
 if not token:
  result['authenticated']=False;print(json.dumps(result));return
 result['authenticated']=True
 for item in value['files']:
  try:
   async with bot._http_client_context() as http:
    response=await http.post('https://oapi.dingtalk.com/media/upload',params={'access_token':token,'type':item['type']},files={'media':(item['name'],base64.b64decode(item['bytes']),item['mime'])},timeout=30)
   data=response.json();result['uploads'].append({'type':item['type'],'name':item['name'],'http_status':response.status_code,'error_code':data.get('errcode'),'uploaded':data.get('errcode')==0 and bool(data.get('media_id'))})
  except Exception as error:result['uploads'].append({'type':item['type'],'uploaded':False,'error_type':type(error).__name__})
 print(json.dumps(result))
asyncio.run(run())'''
completed=subprocess.run([DOCKER,'exec','-i','-e','PYTHONPATH=/app/src','workrag-langbot-1','/app/.venv/bin/python','-c',code],
    input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=100)
if completed.returncode:raise RuntimeError('Media probe failed; private upstream output suppressed')
report=json.loads(completed.stdout.strip().splitlines()[-1])
(RUNTIME/'dingtalk-demo-media-upload.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
