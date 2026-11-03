"""Deploy real status/deltas without switching the unvalidated cloud template."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT/'data/manuals/runtime'
ADAPTER = '/app/src/langbot/pkg/platform/adapters/dingtalk'
CHAT = '/app/src/langbot/pkg/pipeline/process/handlers/chat.py'
NATIVE_MARK = '# work-knowledge-card-v1 bootstrap'
STREAM_MARK = '# work-knowledge-streaming bootstrap'


def run(*args):
    return subprocess.run(list(args),check=True,capture_output=True,text=True,timeout=90).stdout.strip()


def patch_chat(text):
    if '# work-knowledge-immediate-status' in text:
        return text
    old = '                    results = coalesce_stream_results(results)'
    new = '''                    # work-knowledge-immediate-status
                    from ....platform.adapters.dingtalk.knowledge_card.streaming import prime
                    results = prime(results, query, provider_message.MessageChunk)
                    results = coalesce_stream_results(results)'''
    assert text.count(old)==1, 'Chat handler changed; review before deployment'
    text=text.replace(old,new)
    anchor="                yield entities.StageProcessResult(\n                    result_type=entities.ResultType.INTERRUPT,\n                    new_query=query,\n                    user_notice=user_notice,"
    replacement='''                # Close an acknowledged card even if daemon/context setup fails.
                if is_stream and is_create_card:
                    try:
                        from ....platform.adapters.dingtalk.knowledge_card.streaming import fail_card
                        from langbot_plugin.api.entities.builtin.platform import message as _platform_message
                        if await fail_card(query, str(resp_message_id), provider_message.MessageChunk,
                                           _platform_message.Plain, _platform_message.MessageChain):
                            user_notice = None
                    except Exception:
                        self.ap.logger.warning('Could not close work knowledge status card')

'''+anchor
    assert text.count(anchor)==1, 'Exception handling changed; review before deployment'
    text=text.replace(anchor,replacement)
    compile(text,'chat.py','exec')
    return text


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--deploy',action='store_true')
    parser.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    if not args.deploy and not args.rollback:
        print('Use --deploy to install; current cloud template ID is retained.')
        return
    location=RUNTIME/'knowledge-streaming-install.private.json'
    if args.rollback:
        saved=json.loads(location.read_text(encoding='utf-8'))
        for item in saved['files']:
            if item['container']:
                run('docker','cp',item['backup'],f"{item['container']}:{item['target']}")
            else:
                shutil.copy2(item['backup'],item['target'])
        print('Restored previous source. Restart LangBot, plugin runtime and daemon.')
        return
    discover="from pathlib import Path; import yaml; print(next(str(p.parent) for p in Path('/app/data/plugin-runtime/artifacts/sha256').glob('*/code/manifest.yaml') if yaml.safe_load(p.read_text()).get('metadata',{}).get('name')=='CodexAgent'))"
    artifact=run('docker','exec','langbot_plugin_runtime','/app/.venv/bin/python','-c',discover)
    assert artifact.startswith('/app/data/plugin-runtime/artifacts/sha256/') and artifact.endswith('/code')
    backup=RUNTIME/('streaming-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True)
    local=RUNTIME/'langbot-codex/official-plugin/pkg/native_cli.py'
    targets=[('langbot',f'{ADAPTER}/adapter.py','adapter.py'),
             ('langbot',CHAT,'chat.py'),
             ('langbot_plugin_runtime',f'{artifact}/pkg/native_cli.py','native.py'),
             ('',str(local),'local-native.py')]
    saved=[]
    for container,target,name in targets:
        file=backup/name
        if container: run('docker','cp',f'{container}:{target}',str(file))
        else: shutil.copy2(target,file)
        saved.append({'container':container,'target':target,'backup':str(file)})
    # Preflight every exact patch and compile before writing any live code.
    patched=[]
    for item in saved:
        text=Path(item['backup']).read_text(encoding='utf-8')
        if item['target']==CHAT:
            text=patch_chat(text)
        elif item['target'].endswith('adapter.py'):
            if STREAM_MARK not in text:
                text+='\n'+STREAM_MARK+'\nfrom .knowledge_card.streaming import install as _install_work_stream\n_install_work_stream(DingTalkAdapter, platform_message.Plain, platform_message.MessageChain)\n'
        elif NATIVE_MARK not in text:
            text+='\n'+NATIVE_MARK+'\nfrom .knowledge_card.codex_delta import install as _install_work_card\n_install_work_card(_CodexAppServerClient, NativeCodexRunner, RunnerResult)\n'
        compile(text,item['target'],'exec')
        file=backup/(Path(item['backup']).stem+'.patched.py')
        file.write_text(text,encoding='utf-8')
        patched.append((item,file))
    if not location.exists():
        location.write_text(json.dumps({'files':saved},ensure_ascii=False,indent=2),encoding='utf-8')
    helpers=ROOT/'scripts/knowledge_card'
    for container,path in [('langbot',f'{ADAPTER}/knowledge_card'),
                            ('langbot_plugin_runtime',f'{artifact}/pkg/knowledge_card')]:
        run('docker','exec',container,'mkdir','-p',path)
        for file in helpers.glob('*.py'):
            run('docker','cp',str(file),f'{container}:{path}/{file.name}')
    shutil.copytree(helpers,local.parent/'knowledge_card',dirs_exist_ok=True,
        ignore=shutil.ignore_patterns('__pycache__','preview.html'))
    for item,file in patched:
        if item['container']: run('docker','cp',str(file),f"{item['container']}:{item['target']}")
        else: shutil.copy2(file,item['target'])
    print('Installed real streaming/status hooks. Cloud template and bot configuration unchanged.')
    print('Restart langbot, langbot_plugin_runtime and the local daemon to load changes.')


if __name__=='__main__': main()
