"""Deploy the opt-in text transport only after a successful private API probe."""
import argparse
import json
import subprocess
import sys
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,DOCKER,client,data

def restore():
    """Restore an already-enabled transport after a container recreation."""
    code=r'''
from pathlib import Path
import json,sys
module=sys.stdin.read();config=Path('/app/data/workrag-a2ui-config.json')
if not config.exists() or not json.loads(config.read_text()).get('enabled'):
 print(json.dumps({'changed':False}));raise SystemExit(0)
root=Path('/app/src/langbot/libs/dingtalk_api');target=root/'api.py';source=target.read_text()
hook='\n# WorkRAG opt-in A2UI text transport\nfrom .workrag_a2ui_bridge import install as _workrag_install_a2ui\n_workrag_install_a2ui(DingTalkClient)\n'
helper=root/'workrag_a2ui_bridge.py';changed=False
compile(module,str(helper),'exec')
if not helper.exists() or helper.read_text()!=module:helper.write_text(module);changed=True
if '# WorkRAG opt-in A2UI text transport' not in source:
 backup=Path('/app/data/workrag-a2ui-api-original.py')
 if not backup.exists():backup.write_text(source)
 compile(source+hook,str(target),'exec');target.write_text(source+hook);changed=True
adapter=Path('/app/src/langbot/pkg/platform/adapters/dingtalk/adapter.py');text=adapter.read_text()
old="return is_stream_card_configured(self.config)"
new="from langbot.libs.dingtalk_api.workrag_a2ui_bridge import enabled_for_config\n        return is_stream_card_configured(self.config) or enabled_for_config(self.config)"
if 'or enabled_for_config(self.config)' not in text:
 if text.count(old)!=1:raise RuntimeError('Adapter layout changed')
 backup=Path('/app/data/workrag-a2ui-adapter-original.py')
 if not backup.exists():backup.write_text(text)
 modified=text.replace(old,new);compile(modified,str(adapter),'exec');adapter.write_text(modified);changed=True
print(json.dumps({'changed':changed}))
'''
    result=subprocess.run([DOCKER,'exec','-i','workrag-langbot-1','/app/.venv/bin/python','-c',code],
        input=(ROOT/'deployment/dingtalk_a2ui_bridge.py').read_text(encoding='utf-8'),capture_output=True,text=True,encoding='utf-8',check=True)
    return json.loads(result.stdout)['changed']

def install(enabled):
    if not enabled:
        code="from pathlib import Path; import json; p=Path('/app/data/workrag-a2ui-config.json'); d=json.loads(p.read_text()) if p.exists() else {}; d['enabled']=False; p.write_text(json.dumps(d)); print('A2UI disabled; future replies use original cards')"
        subprocess.run([DOCKER,'exec','workrag-langbot-1','/app/.venv/bin/python','-c',code],check=True);return
    probe=json.loads((RUNTIME/'a2ui-private-access.private.json').read_text(encoding='utf-8'))
    if probe.get('http_status')!=200 or probe.get('business_success') is not True or probe.get('finish_business_success') is not True:
        raise RuntimeError('A2UI API access is not verified; enable AICard.Instance.Write and repeat the private probe first')
    deliveries=probe.get('delivery_results',[])
    if not deliveries or not all(r.get('success') is True for r in deliveries):
        raise RuntimeError('Private delivery has not been confirmed by the platform')
    sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
    from workrag_agent.store import Store
    bot_id='37416bec-870f-4ecc-9ac7-c2ddbc16123d';bot=data(client().get('/api/v1/platform/bots/'+bot_id))['bot']
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    with store.connection() as conn:
        rows=conn.execute("SELECT DISTINCT s.identity->>'sender' AS sender FROM wa_answers a JOIN wa_sessions s USING(session_key) WHERE a.question=%s AND s.identity->>'bot'=%s",('资料联调开始',bot_id)).fetchall()
    if len(rows)!=1:raise RuntimeError('Private tester is ambiguous')
    payload={'module':(ROOT/'deployment/dingtalk_a2ui_bridge.py').read_text(encoding='utf-8'),
      'template':json.loads((RUNTIME/'card-json-v2/workrag-card.a2ui.json').read_text(encoding='utf-8')),
      'config':{'enabled':True,'client_id':bot['adapter_config']['client_id'],'private_tester':rows[0]['sender']}}
    code=r'''
from pathlib import Path
import json,sys
d=json.load(sys.stdin);root=Path('/app/src/langbot/libs/dingtalk_api');target=root/'api.py';source=target.read_text()
hook='\n# WorkRAG opt-in A2UI text transport\nfrom .workrag_a2ui_bridge import install as _workrag_install_a2ui\n_workrag_install_a2ui(DingTalkClient)\n'
compile(d['module'],'workrag_a2ui_bridge.py','exec')
if '# WorkRAG opt-in A2UI text transport' not in source:
 backup=Path('/app/data/workrag-a2ui-api-original.py')
 if not backup.exists():backup.write_text(source)
 compile(source+hook,str(target),'exec');target.write_text(source+hook)
(root/'workrag_a2ui_bridge.py').write_text(d['module'])
Path('/app/data/workrag-a2ui-template.json').write_text(json.dumps(d['template']))
Path('/app/data/workrag-a2ui-config.json').write_text(json.dumps(d['config']))
print('A2UI text transport installed for the confirmed private tester; restart Host to activate')
'''
    subprocess.run([DOCKER,'exec','-i','workrag-langbot-1','/app/.venv/bin/python','-c',code],
                   input=json.dumps(payload),text=True,check=True)
    restore()

if __name__=='__main__':
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--enable',action='store_true');group.add_argument('--disable',action='store_true')
    install(parser.parse_args().enable)
