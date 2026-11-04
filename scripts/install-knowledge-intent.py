"""Install narrow Host hooks, with independent backups and exact compile checks."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'data/manuals/runtime'
PACKAGE='/app/src/langbot/pkg/platform/adapters/dingtalk/knowledge_card'
HOOKS={
    '/app/src/langbot/pkg/agent/runner/query_bridge.py':('install_query_bridge','QueryRunBridge'),
    '/app/src/langbot/pkg/agent/runner/resource_builder.py':('install_resource_builder','AgentResourceBuilder'),
}
MARK='# work-knowledge-intent-v1 bootstrap'


def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=90).stdout.strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--deploy',action='store_true');parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    if not args.deploy and not args.rollback:raise SystemExit('Specify --deploy or --rollback')
    record=RUNTIME/'intent-install.private.json'
    if args.rollback:
        saved=json.loads(record.read_text(encoding='utf-8'))
        for item in saved['files']:run('docker','cp',item['backup'],'langbot:'+item['target'])
        print('Restored Host sources; set mode off and restart LangBot to unload hooks.');return
    folder=RUNTIME/('intent-install-'+datetime.now().strftime('%Y%m%d-%H%M%S'));folder.mkdir(parents=True)
    files=[]
    for target,(install,cls) in HOOKS.items():
        backup=folder/Path(target).name;run('docker','cp','langbot:'+target,str(backup))
        text=backup.read_text(encoding='utf-8')
        assert f'class {cls}' in text
        if MARK not in text:text+='\n'+MARK+f'\nfrom langbot.pkg.platform.adapters.dingtalk.knowledge_card.intent_host import {install} as _install_work_intent\n_install_work_intent({cls})\n'
        compile(text,target,'exec');patched=backup.with_suffix('.patched.py');patched.write_text(text,encoding='utf-8')
        files.append({'target':target,'backup':str(backup),'patched':str(patched)})
    # Streaming wrapper keeps immediate acknowledgement and the existing final writer.
    target=PACKAGE+'/streaming.py';backup=folder/'streaming.py';run('docker','cp','langbot:'+target,str(backup))
    compile((ROOT/'scripts/knowledge_card/streaming.py').read_text(encoding='utf-8'),target,'exec')
    files.append({'target':target,'backup':str(backup),'patched':str(ROOT/'scripts/knowledge_card/streaming.py')})
    if not record.exists():record.write_text(json.dumps({'files':files},ensure_ascii=False,indent=2),encoding='utf-8')
    run('docker','cp',str(ROOT/'scripts/knowledge_card/deployment.py'),'langbot:'+PACKAGE+'/deployment.py')
    run('docker','cp',str(ROOT/'scripts/knowledge_card/intent_host.py'),'langbot:'+PACKAGE+'/intent_host.py')
    run('docker','cp',str(ROOT/'scripts/knowledge_card/session_memory.py'),'langbot:'+PACKAGE+'/session_memory.py')
    for item in files:run('docker','cp',item['patched'],'langbot:'+item['target'])
    print('Installed Host hooks. Current template retained. Restart only LangBot to load hooks; mode remains shadow/off.')


if __name__=='__main__':main()
