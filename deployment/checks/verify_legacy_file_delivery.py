"""Verify the old adapter's final File chain in the authorized private chat."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import base64
import json
import subprocess
import sys
from uuid import uuid4
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,DOCKER,client,data

def verify(images=False):
    receipt=RUNTIME/('legacy-image-adapter-acceptance.private.json' if images else 'legacy-file-adapter-acceptance.private.json')
    if receipt.exists():print('Existing file verification found; no duplicate sent');return
    sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
    from workrag_agent.store import Store
    from workrag_agent.tools import Backend
    from workrag_agent.media import prepare_media
    bot_id='37416bec-870f-4ecc-9ac7-c2ddbc16123d';cfg=data(client().get('/api/v1/platform/bots/'+bot_id))['bot']['adapter_config']
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    with store.connection() as c:
        rows=c.execute("SELECT DISTINCT s.identity->>'sender' AS sender FROM wa_answers a JOIN wa_sessions s USING(session_key) WHERE a.question=%s AND s.identity->>'bot'=%s",('资料联调开始',bot_id)).fetchall()
    if len(rows)!=1:raise ValueError('Ambiguous tester')
    doc=json.loads((RUNTIME/'demo-materials.json').read_text(encoding='utf-8'))['documents'][0]
    backend=Backend()
    if images:
        packets=backend.followup('images',doc['entry_id'],doc['version'],'需要图片')
        pictures=[image for r in packets.get('results',[]) for image in r.get('metadata',{}).get('images',[])]
        requests=[{'kind':'images','entry_id':doc['entry_id'],'version':doc['version'],'images':pictures}]
    else:requests=[{'kind':'source_file','entry_id':doc['entry_id'],'version':doc['version'],'name':'WRAG-DEMO-EQUIP-01.docx'}]
    parts,_=prepare_media(backend,requests,[doc['entry_id']])
    assert parts
    receipt.write_text(json.dumps({'attempt_started':True,'result_unknown':True}),encoding='utf-8')
    payload={'cfg':cfg,'actor':rows[0]['sender'],'parts':parts,'text':'【演示图片验收】设备借用演练配图，请点击“相关图片”展开。' if images else '【演示附件验收】设备借用演练的 Word 原文件；虚构测试资料，不是公司正式制度。'}
    code=r'''
import sys,json,asyncio,logging
from uuid import uuid4
from types import SimpleNamespace
from langbot.libs.dingtalk_api.api import DingTalkClient
from langbot.pkg.platform.adapters.dingtalk.adapter import DingTalkAdapter
from langbot_plugin.api.entities.builtin.platform.message import MessageChain,Plain,File
from langbot_plugin.api.entities.builtin.provider.message import MessageChunk,Message
logging.disable(logging.CRITICAL)
async def main():
 d=json.load(sys.stdin);cfg=d['cfg'];bot=DingTalkClient(cfg['client_id'],cfg['client_secret'],'WorkRAG',cfg['client_id'],True,None)
 incoming=SimpleNamespace(conversation_type='1',sender_staff_id=d['actor'],conversation_id='',message_type='text',get_text_list=lambda:['演示原文件验收'])
 source=SimpleNamespace(source_platform_object=SimpleNamespace(incoming_message=incoming))
 adapter=DingTalkAdapter.model_construct(config=cfg,bot=bot);reply=uuid4().hex
 try:
  await adapter.create_message_card(reply,source)
  text=d['text']
  msg=Message(role='assistant',content=[{'type':'text','text':text},*d['parts']])._get_content_platform_message_chain()
  await adapter.reply_message_chunk(source,MessageChunk(role='assistant',content=text,resp_message_id=reply),msg,is_final=True)
  print(json.dumps({'old_card_created':True,'native_output_returned':True,'resource_count':len(d['parts']),'user_received_verified':False}))
 except Exception as e:print(json.dumps({'old_card_created':False,'native_file_send_returned':False,'error_type':type(e).__name__,'user_received_verified':False}))
asyncio.run(main())
'''
    run=subprocess.run([DOCKER,'exec','-i','-e','PYTHONPATH=/app/src','workrag-langbot-1','/app/.venv/bin/python','-c',code],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',timeout=100)
    if run.returncode:raise RuntimeError('File acceptance outcome unknown; do not retry automatically')
    result=json.loads(run.stdout.strip().splitlines()[-1]);receipt.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--images',action='store_true');verify(parser.parse_args().images)
