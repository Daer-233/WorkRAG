"""Prepare by default. Activation requires a separately imported/validated template.

Never replaces the existing permission patches or upgrades CodexAgent artifacts.
Backups containing credentials stay under the ignored private runtime directory.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/knowledge-card-v1'
RUNTIME = ROOT / 'data/manuals/runtime'
ADAPTER = '/app/src/langbot/pkg/platform/adapters/dingtalk'
MARK = '# work-knowledge-card-v1 bootstrap'
NATIVE_HOOK = '\n' + MARK + '\nfrom .knowledge_card.codex_delta import install as _install_work_card\n_install_work_card(_CodexAppServerClient, NativeCodexRunner, RunnerResult)\n'
ADAPTER_HOOK = '\n' + MARK + '\nfrom .knowledge_card.adapter import install as _install_work_card\n_install_work_card(DingTalkAdapter)\n'


def run(*args):
    return subprocess.run(list(args),check=True,capture_output=True,text=True).stdout.strip()


def append_hook(source,hook):
    if MARK not in source: source += hook
    compile(source,'patched.py','exec')
    return source


def connection():
    spec=importlib.util.spec_from_file_location('connection',ROOT/'scripts/connect-langbot-knowledge.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--activate',metavar='TEMPLATE_ID')
    parser.add_argument('--validated',action='store_true')
    parser.add_argument('--rollback',action='store_true')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    destination=OUT/'package/knowledge_card'
    shutil.copytree(ROOT/'scripts/knowledge_card',destination,dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__','preview.html'))
    shutil.copy2(ROOT/'scripts/knowledge_dingtalk_media.py',OUT/'package/knowledge_media.py')
    manifest={str(p.relative_to(OUT/'package')):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (OUT/'package').rglob('*.py')}
    for p in (OUT/'package').rglob('*.py'): compile(p.read_text(encoding='utf-8'),str(p),'exec')
    (OUT/'package.sha256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    if not args.activate and not args.rollback:
        print('Prepared package. Active services, bot routing and template unchanged.')
        return
    if args.activate and not args.validated:
        raise SystemExit('Import and validate the new template first; activation requires --validated.')
    import httpx
    conn=connection()
    bot_id='9777ca2e-7df1-4441-84ca-abedd4bc5c01'
    backup=RUNTIME/'knowledge-card-activation.private.json'
    with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':conn.credential()},timeout=60) as client:
        bot=conn.data(client.get(f'/api/v1/platform/bots/{bot_id}'))['bot']
        config=dict(bot['adapter_config'])
        if args.rollback:
            saved=json.loads(backup.read_text(encoding='utf-8'))
            config['card_template_id']=saved['old_template_id']
            conn.data(client.put(f'/api/v1/platform/bots/{bot_id}',json={'adapter_config':config}))
            run('docker','exec','langbot','/app/.venv/bin/python','-c',
                "from pathlib import Path; Path('/app/data/work-knowledge-card-v1.json').unlink(missing_ok=True)")
            # Hooks delegate to the original adapter while the gate is disabled.
            print('Previous template restored. Restart langbot; Codex delta compatibility hook remains installed.')
            return
        if config.get('card_template_id') == args.activate and not backup.exists():
            raise SystemExit('New template must differ from the unbacked current template.')
        discover="from pathlib import Path; import yaml; print(next(str(p.parent) for p in Path('/app/data/plugin-runtime/artifacts/sha256').glob('*/code/manifest.yaml') if yaml.safe_load(p.read_text()).get('metadata',{}).get('name')=='CodexAgent'))"
        artifact=run('docker','exec','langbot_plugin_runtime','/app/.venv/bin/python','-c',discover)
        assert artifact.startswith('/app/data/plugin-runtime/artifacts/sha256/') and artifact.endswith('/code')
        local=RUNTIME/'langbot-codex/official-plugin/pkg/native_cli.py'
        host_native=RUNTIME/'card-native.before.py'
        adapter_file=RUNTIME/'card-adapter.before.py'
        run('docker','cp',f'langbot_plugin_runtime:{artifact}/pkg/native_cli.py',str(host_native))
        run('docker','cp',f'langbot:{ADAPTER}/adapter.py',str(adapter_file))
        if not backup.exists():
            backup.write_text(json.dumps({'old_template_id':config.get('card_template_id'),
                'artifact':artifact,'bot_id':bot_id},ensure_ascii=False,indent=2),encoding='utf-8')
            shutil.copy2(local,RUNTIME/'card-local-native.before.py')
        # Copy compatible helpers before enabling their imports.
        run('docker','exec','langbot','mkdir','-p',f'{ADAPTER}/knowledge_card')
        run('docker','exec','langbot_plugin_runtime','mkdir','-p',f'{artifact}/pkg/knowledge_card')
        run('docker','cp',str(destination)+'/.',f'langbot:{ADAPTER}/knowledge_card')
        run('docker','cp',str(OUT/'package/knowledge_media.py'),f'langbot:{ADAPTER}/knowledge_media.py')
        run('docker','cp',str(destination)+'/.',f'langbot_plugin_runtime:{artifact}/pkg/knowledge_card')
        shutil.copytree(destination,local.parent/'knowledge_card',dirs_exist_ok=True)
        for file,hook,target in ((host_native,NATIVE_HOOK,f'langbot_plugin_runtime:{artifact}/pkg/native_cli.py'),
                                  (adapter_file,ADAPTER_HOOK,f'langbot:{ADAPTER}/adapter.py')):
            patched=RUNTIME/(file.stem+'.patched.py')
            patched.write_text(append_hook(file.read_text(encoding='utf-8'),hook),encoding='utf-8')
            run('docker','cp',str(patched),target)
        local.write_text(append_hook(local.read_text(encoding='utf-8'),NATIVE_HOOK),encoding='utf-8')
        gate=RUNTIME/'work-knowledge-card-v1.json'
        gate.write_text(json.dumps({'template_id':args.activate,'validated':True}),encoding='utf-8')
        run('docker','cp',str(gate),'langbot:/app/data/work-knowledge-card-v1.json')
        config['card_template_id']=args.activate
        conn.data(client.put(f'/api/v1/platform/bots/{bot_id}',json={'adapter_config':config}))
    print('Installed for LSD AI助手. Restart langbot, plugin runtime and the local Codex daemon during rollout; see handoff.')


if __name__=='__main__': main()
