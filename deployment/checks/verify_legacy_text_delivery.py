"""One marked text-only test in the user's previously authorized private chat."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
import subprocess
import sys
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,DOCKER,client,data


def verify():
    receipt=RUNTIME/'legacy-state-aware-text-acceptance.private.json'
    if receipt.exists():
        print('A test was already attempted; inspect the receipt, do not duplicate automatically');return
    sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
    from workrag_agent.store import Store
    bot_id='37416bec-870f-4ecc-9ac7-c2ddbc16123d'
    cfg=data(client().get('/api/v1/platform/bots/'+bot_id))['bot']['adapter_config']
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    with store.connection() as conn:
        rows=conn.execute("SELECT DISTINCT s.identity->>'sender' AS sender FROM wa_answers a JOIN wa_sessions s USING(session_key) WHERE a.question=%s AND s.identity->>'bot'=%s",('资料联调开始',bot_id)).fetchall()
    if len(rows)!=1:raise RuntimeError('Private tester is not unique; nothing sent')
    receipt.write_text(json.dumps({'attempt_started':True,'outcome_unknown':True}),encoding='utf-8')
    code=r'''
import sys,json,asyncio,logging,time
from uuid import uuid4
from types import SimpleNamespace
from langbot.libs.dingtalk_api.api import DingTalkClient
from langbot.pkg.platform.adapters.dingtalk.adapter import DingTalkAdapter
from langbot_plugin.api.entities.builtin.platform.message import MessageChain,Plain
from langbot_plugin.api.entities.builtin.provider.message import MessageChunk
logging.disable(logging.CRITICAL)
async def main():
 d=json.load(sys.stdin);cfg=d['cfg'];bot=DingTalkClient(cfg['client_id'],cfg['client_secret'],'WorkRAG',cfg['client_id'],True,None)
 incoming=SimpleNamespace(conversation_type='1',sender_staff_id=d['actor'],conversation_id='',message_type='text',get_text_list=lambda:['现有模板更新验收'])
 source=SimpleNamespace(source_platform_object=SimpleNamespace(incoming_message=incoming))
 adapter=DingTalkAdapter.model_construct(config=cfg,bot=bot);reply=uuid4().hex;timings=[]
 try:
  await adapter.create_message_card(reply,source)
  text='【现有模板更新验收】\n'
  for sentence in ['第一段：这条消息使用你当前的旧模板。\n','第二段：生成中只更新当前可见的正文通道。\n','第三段：切到完成态前再补齐流式组件正文，避免空白。\n']:
   text+=sentence;began=time.monotonic()
   await adapter.reply_message_chunk(source,MessageChunk(role='assistant',content=text,resp_message_id=reply),MessageChain([Plain(text=text)]),is_final=False)
   timings.append(round(time.monotonic()-began,3));await asyncio.sleep(.8)
  text+='图片折叠和文件通道保留。请确认上面三段在完成后仍然可见。'
  began=time.monotonic()
  await adapter.reply_message_chunk(source,MessageChunk(role='assistant',content=text,resp_message_id=reply),MessageChain([Plain(text=text)]),is_final=True)
  print(json.dumps({'platform_updates_accepted':True,'interim_update_seconds':timings,'final_update_seconds':round(time.monotonic()-began,3),'client_visible_confirmed':False,'template_changed':False}))
 except Exception as e:
  print(json.dumps({'platform_updates_accepted':False,'outcome_unknown':True,'error_type':type(e).__name__,'client_visible_confirmed':False}))
asyncio.run(main())
'''
    run=subprocess.run([DOCKER,'exec','-i','-e','PYTHONPATH=/app/src','workrag-langbot-1','/app/.venv/bin/python','-c',code],
        input=json.dumps({'cfg':cfg,'actor':rows[0]['sender']}),capture_output=True,text=True,encoding='utf-8',timeout=100)
    if run.returncode:raise RuntimeError('Outcome unknown; sensitive output suppressed; do not retry automatically')
    result=json.loads(run.stdout.strip().splitlines()[-1])
    receipt.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    assert result.get('platform_updates_accepted'), 'DingTalk text acceptance failed'

if __name__=='__main__':verify()
