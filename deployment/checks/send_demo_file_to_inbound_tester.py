"""One explicit test file to the user who sent the agreed private-chat phrase."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,DOCKER,client,data

sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
from workrag_agent.store import Store
from workrag_agent.tools import Backend

receipt=RUNTIME/'dingtalk-demo-file-send.private.json'
if receipt.exists() and json.loads(receipt.read_text(encoding='utf-8')).get('platform_accepted'):
    print('Previously accepted test send found; no duplicate message sent')
    raise SystemExit(0)
bot=data(client().get('/api/v1/platform/bots'))['bots'][0]
store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
with store.connection() as conn:
    rows=conn.execute('''SELECT s.identity FROM wa_answers a JOIN wa_sessions s USING(session_key)
      WHERE a.question=%s AND s.identity->>'bot'=%s ORDER BY a.created_at DESC''',('资料联调开始',bot['uuid'])).fetchall()
actors={r['identity']['sender'] for r in rows}
if len(actors)!=1:raise RuntimeError('Cannot uniquely identify the explicitly agreed inbound tester; no send attempted')
actor=next(iter(actors))
materials=json.loads((RUNTIME/'demo-materials.json').read_text(encoding='utf-8'));source=materials['documents'][0]
Backend().document(source['entry_id'],source['version'])
file=Path(source['source_file']).resolve();assert file.is_relative_to((ROOT/'data/manuals/runtime/demo-enterprise').resolve()) and file.suffix=='.docx'
payload={'config':bot['adapter_config'],'actor':actor,'name':file.name,'bytes':base64.b64encode(file.read_bytes()).decode()}
code='''import sys,json,asyncio,logging
from types import SimpleNamespace
from langbot.libs.dingtalk_api.api import DingTalkClient
from langbot_plugin.api.entities.builtin.platform.message import File
logging.disable(logging.CRITICAL)
async def main():
 data=json.load(sys.stdin);cfg=data['config'];bot=DingTalkClient(cfg['client_id'],cfg['client_secret'],'WorkRAG demo',cfg['client_id'],True,None)
 try:
  result=await bot.send_attachment(File(name=data['name'],base64=data['bytes']),SimpleNamespace(conversation_type='1',sender_staff_id=data['actor'],conversation_id=''))
  rejected={k:len(result.get(k) or []) for k in ('flowControlledStaffIdList','invalidStaffIdList','filteredStaffIdList')} if isinstance(result,dict) else {}
  print(json.dumps({'platform_accepted':True,'recipient_rejection_counts':rejected,'returned_fields':list(result) if isinstance(result,dict) else [],'file_name':data['name'],'user_received_verified':False}))
 except Exception as error:print(json.dumps({'platform_accepted':False,'error_type':type(error).__name__,'user_received_verified':False}))
asyncio.run(main())'''
run=subprocess.run([DOCKER,'exec','-i','-e','PYTHONPATH=/app/src','workrag-langbot-1','/app/.venv/bin/python','-c',code],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=100)
if run.returncode:raise RuntimeError('Send probe failed; sensitive upstream output suppressed; do not automatically retry')
result=json.loads(run.stdout.strip().splitlines()[-1]);result.update(recipient_sha256=hashlib.sha256(actor.encode()).hexdigest(),source_entry_id=source['entry_id'])
receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
