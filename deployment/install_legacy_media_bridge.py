"""Install native file diagnostics and gated legacy-card image support."""
import argparse
import json
import subprocess
import sys
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,DOCKER,client,data

def restore():
    code=r'''
from pathlib import Path
import sys,json
root=Path('/app/src/langbot');config=Path('/app/data/workrag-legacy-media-config.json')
if not config.exists():print(json.dumps({'changed':False}));raise SystemExit(0)
module=sys.stdin.read();helper=root/'libs/dingtalk_api/workrag_legacy_media_bridge.py';compile(module,str(helper),'exec');changed=False
if not helper.exists() or helper.read_text()!=module:helper.write_text(module);changed=True
for rel,hook in [
 ('libs/dingtalk_api/api.py','\n# WorkRAG legacy media client\nfrom .workrag_legacy_media_bridge import install_client as _workrag_media_client\n_workrag_media_client(DingTalkClient)\n'),
 ('pkg/platform/adapters/dingtalk/adapter.py','\n# WorkRAG legacy media adapter\nfrom langbot.libs.dingtalk_api.workrag_legacy_media_bridge import install_adapter as _workrag_media_adapter\n_workrag_media_adapter(DingTalkAdapter)\n')]:
 p=root/rel;s=p.read_text()
 if hook.strip() not in s:compile(s+hook,str(p),'exec');p.write_text(s+hook);changed=True
print(json.dumps({'changed':changed}))
'''
    result=subprocess.run([DOCKER,'exec','-i','workrag-langbot-1','/app/.venv/bin/python','-c',code],
        input=(ROOT/'deployment/legacy_media_bridge.py').read_text(encoding='utf-8'),capture_output=True,text=True,encoding='utf-8',check=True)
    return json.loads(result.stdout)['changed']

def install(published=False,streaming_answer=False):
    sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
    from workrag_agent.store import Store
    bot_id='37416bec-870f-4ecc-9ac7-c2ddbc16123d'
    bot=data(client().get('/api/v1/platform/bots/'+bot_id))['bot'];cfg=bot['adapter_config']
    if not cfg.get('card_template_id'):raise RuntimeError('A legacy template ID is required')
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    with store.connection() as conn:
        rows=conn.execute("SELECT DISTINCT s.identity->>'sender' AS sender FROM wa_answers a JOIN wa_sessions s USING(session_key) WHERE a.question=%s AND s.identity->>'bot'=%s",('资料联调开始',bot_id)).fetchall()
    if len(rows)!=1:raise RuntimeError('Ambiguous private tester')
    payload={'module':(ROOT/'deployment/legacy_media_bridge.py').read_text(encoding='utf-8'),
      'config':{'client_id':cfg['client_id'],'template_id':cfg['card_template_id'],'private_tester':rows[0]['sender'],
                'folded_template_published':published,'answer_streaming_component':streaming_answer}}
    code=r'''
import sys,json
from pathlib import Path
d=json.load(sys.stdin);root=Path('/app/src/langbot');helper=root/'libs/dingtalk_api/workrag_legacy_media_bridge.py'
compile(d['module'],str(helper),'exec');helper.write_text(d['module'])
for rel,hook,backup in [
 ('libs/dingtalk_api/api.py','\n# WorkRAG legacy media client\nfrom .workrag_legacy_media_bridge import install_client as _workrag_media_client\n_workrag_media_client(DingTalkClient)\n','workrag-media-api-original.py'),
 ('pkg/platform/adapters/dingtalk/adapter.py','\n# WorkRAG legacy media adapter\nfrom langbot.libs.dingtalk_api.workrag_legacy_media_bridge import install_adapter as _workrag_media_adapter\n_workrag_media_adapter(DingTalkAdapter)\n','workrag-media-adapter-original.py')]:
 p=root/rel;s=p.read_text()
 if hook.strip() not in s:
  b=Path('/app/data')/backup
  if not b.exists():b.write_text(s)
  compile(s+hook,str(p),'exec');p.write_text(s+hook)
Path('/app/data/workrag-legacy-media-config.json').write_text(json.dumps(d['config']))
print(json.dumps({'installed':True,'folded_template_published':d['config']['folded_template_published']}))
'''
    subprocess.run([DOCKER,'exec','-i','workrag-langbot-1','/app/.venv/bin/python','-c',code],input=json.dumps(payload),text=True,check=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--folded-template-published',action='store_true')
    parser.add_argument('--streaming-answer-component',action='store_true');args=parser.parse_args()
    install(args.folded_template_published,args.streaming_answer_component)
