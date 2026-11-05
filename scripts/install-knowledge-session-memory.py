"""Install or toggle the conversation-memory Host hooks on the pinned LangBot instance."""
import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'data/manuals/runtime'
CARD = '/app/src/langbot/pkg/platform/adapters/dingtalk/knowledge_card'
HANDLER = '/app/src/langbot/pkg/plugin/handler.py'
ORCHESTRATOR = '/app/src/langbot/pkg/agent/runner/orchestrator.py'
FLAG = '/app/data/work-knowledge-session-memory.json'
IMPORT = 'from langbot.pkg.platform.adapters.dingtalk.knowledge_card import session_memory as _work_memory'
MARKER = '# work-knowledge-session-memory-v1'
BOOTSTRAP = f'''
{MARKER}
{IMPORT}
from langbot.pkg.agent.runner.query_bridge import QueryRunBridge as _MemoryBridge
from langbot.pkg.agent.runner.resource_builder import AgentResourceBuilder as _MemoryBuilder
from langbot.pkg.agent.runner.session_registry import AgentRunSessionRegistry as _MemoryRegistry
_work_memory.install(_MemoryBridge, _MemoryBuilder, _MemoryRegistry)
'''
NATIVE_BOOTSTRAP = '\n# work-knowledge-session-memory-native-v1\n_work_memory.install_native(AgentRunOrchestrator)\n'


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True,
                          text=True, encoding='utf-8', timeout=90).stdout.strip()


def patch_handler(source):
    if MARKER in source:
        return source
    tree = ast.parse(source)
    edits = []
    for name, action in [('retrieve_knowledge', 'RETRIEVE_KNOWLEDGE'),
                         ('retrieve_knowledge_base', 'RETRIEVE_KNOWLEDGE_BASE')]:
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == name and any(ast.unparse(item) == f'self.action(PluginToRuntimeAction.{action})'
                                                   for item in node.decorator_list)]
        if len(functions) != 1:
            raise ValueError(f'Unexpected LangBot retrieval handler for {action}')
        function = functions[0]
        authorization = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Name) and node.func.id == '_validate_run_authorization']
        kb = [node for node in function.body if isinstance(node, ast.Assign)
              and ast.unparse(node.targets[0]) == 'kb']
        results = [node for node in ast.walk(function) if isinstance(node, ast.Assign)
                   and ast.unparse(node.targets[0]) == 'results']
        if not (len(authorization) == len(kb) == len(results) == 1
                and authorization[0].lineno < kb[0].lineno < results[0].lineno):
            raise ValueError(f'Cannot locate the authorized retrieval path for {action}')
        edits.append((kb[0].lineno - 1, [f'            {MARKER}', f'            {IMPORT}',
                      '            memory_session = session if run_id else None',
                      '            query_text, top_k, filters = _work_memory.scoped_query(',
                      '                memory_session, kb_id, query_text, top_k, filters)', '']))
        edits.append((results[0].end_lineno, ['                _work_memory.capture(memory_session, kb_id, results)']))
    lines = source.splitlines()
    for offset, extra in sorted(edits, reverse=True):
        lines[offset:offset] = extra
    return '\n'.join(lines) + '\n'


def flag(value, storage='memory'):
    docker('exec', 'langbot', '/app/.venv/bin/python', '-c',
           'import json,sys; from pathlib import Path; '
           'p=Path(sys.argv[1]); t=p.with_suffix(".tmp"); '
           'd=json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}; '
           'd.update(enabled=sys.argv[2]=="on",storage=sys.argv[3]); '
           't.write_text(json.dumps(d),encoding="utf-8"); t.replace(p)',
           FLAG, 'on' if value else 'off', storage)


def provision_postgres_token():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    token = RUNTIME / 'session-memory-token.private'
    try:
        with token.open('x', encoding='ascii') as file:
            file.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    if len(token.read_text(encoding='ascii').strip()) < 32:
        raise RuntimeError('Invalid session memory credential file')
    docker('cp', str(token), 'langbot:/app/data/work-knowledge-session-memory-token')


def link_training_photos():
    client = build_opener(ProxyHandler({}))
    with client.open('http://127.0.0.1:8060/api/v1/manuals/entries', timeout=8) as response:
        rows = json.load(response)
    selected = []
    for title in ('AI赋能设计培训回顾', 'AI赋能设计培训回顾｜现场照片'):
        matches = [row for row in rows if row['title'] == title and row['status'] == 'published'
                   and row['processing_status'] == 'ready']
        if len(matches) != 1:
            raise RuntimeError(f'需要一份唯一且已发布的资料《{title}》')
        selected.append(matches[0])
    article, photos = selected
    target = ROOT / 'data/manuals/session-memory-photo-links.json'
    current = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    current[str(article['id'])] = {'source_version': article.get('version') or '',
                                   'entry_id': str(photos['id']), 'version': photos.get('version') or ''}
    pending = target.with_suffix('.tmp')
    pending.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
    pending.replace(target)
    print('Linked the published training article to its published photo album.')


def install():
    record = RUNTIME / 'session-memory-install.private.json'
    folder = RUNTIME / ('session-memory-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    folder.mkdir(parents=True)
    changes = []
    def patch_orchestrator(source):
        if MARKER not in source:
            source += '\n' + BOOTSTRAP
        if NATIVE_BOOTSTRAP.strip() not in source:
            source += NATIVE_BOOTSTRAP
        return source

    for target, transform in [(HANDLER, patch_handler), (ORCHESTRATOR, patch_orchestrator),
            (CARD + '/streaming.py', lambda _: (ROOT / 'scripts/knowledge_card/streaming.py').read_text(encoding='utf-8'))]:
        backup = folder / Path(target).name
        docker('cp', f'langbot:{target}', str(backup))
        patched = backup.with_suffix('.patched.py')
        contents = transform(backup.read_text(encoding='utf-8'))
        compile(contents, target, 'exec')
        patched.write_text(contents, encoding='utf-8')
        changes.append((str(backup), str(patched), target))
    module = ROOT / 'scripts/knowledge_card/session_memory.py'
    compile(module.read_text(encoding='utf-8'), str(module), 'exec')
    flag(False)
    if not record.exists():
        record.write_text(json.dumps(changes, ensure_ascii=False, indent=2), encoding='utf-8')
    docker('cp', str(module), f'langbot:{CARD}/session_memory.py')
    identity_module = ROOT / 'scripts/knowledge_card/department_identity.py'
    compile(identity_module.read_text(encoding='utf-8'), str(identity_module), 'exec')
    docker('cp', str(identity_module), f'langbot:{CARD}/department_identity.py')
    installed = []
    try:
        for backup, patched, target in changes:
            docker('cp', patched, f'langbot:{target}')
            installed.append((backup, target))
    except subprocess.SubprocessError:
        for backup, target in reversed(installed):
            docker('cp', backup, f'langbot:{target}')
        raise
    print('Installed with memory off. Restart LangBot, then run the synthetic Host checks.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('install', 'enable', 'enable-postgres', 'provision-postgres', 'disable', 'rollback', 'link-training-photos'))
    args = parser.parse_args()
    if args.action == 'install':
        install()
    elif args.action == 'link-training-photos':
        link_training_photos()
    elif args.action == 'provision-postgres':
        provision_postgres_token()
    elif args.action == 'rollback':
        flag(False)
        record = RUNTIME / 'session-memory-install.private.json'
        for backup, _, target in json.loads(record.read_text(encoding='utf-8')):
            docker('cp', backup, f'langbot:{target}')
        print('Restored previous sources. Restart LangBot to unload the hooks.')
    else:
        if args.action in {'enable', 'enable-postgres'}:
            postgres = args.action == 'enable-postgres'
            result = docker('exec', 'langbot', '/app/.venv/bin/python', '/tmp/verify-work-session-memory.py',
                            *(['--postgres'] if postgres else []))
            print(result)
            flag(True, 'postgres' if postgres else 'memory')
        else:
            flag(False)
        print(f'Session memory: {args.action}')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr, file=sys.stderr)
        raise SystemExit(error.returncode)
