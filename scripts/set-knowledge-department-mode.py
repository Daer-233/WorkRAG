"""Switch department authorization without changing knowledge data."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BACKEND_FLAG = ROOT / 'data/manuals/runtime/department-enforced.json'
HOST_FLAG = '/app/data/work-knowledge-session-memory.json'


def host_mode(mode):
    code = ('import json,sys; from pathlib import Path; '
            'p=Path(sys.argv[1]); d=json.loads(p.read_text(encoding="utf-8")); '
            'd["department_mode"]=sys.argv[2]; d["department_shadow"]=True; '
            't=p.with_suffix(".tmp"); t.write_text(json.dumps(d),encoding="utf-8"); t.replace(p)')
    subprocess.run(['docker', 'exec', 'langbot', '/app/.venv/bin/python', '-c', code, HOST_FLAG, mode],
                   check=True, timeout=60)


def check_ready():
    code = ('import json,sys; from pathlib import Path; '
            'd=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); '
            'sys.exit(0 if d.get("enabled") is True and d.get("storage")=="postgres" else 1)')
    subprocess.run(['docker', 'exec', 'langbot', '/app/.venv/bin/python', '-c', code, HOST_FLAG],
                   check=True, timeout=60)
    import httpx
    with httpx.Client(base_url='http://127.0.0.1:8060', timeout=10, trust_env=False) as client:
        client.get('/health').raise_for_status()
        scopes = client.get('/api/v1/manuals/departments/entries/scopes').raise_for_status().json()
        if not any(item.get('confirmed') for item in scopes):
            raise RuntimeError('没有已确认范围的资料，无法启用部门检索')


def backend_mode(enabled):
    BACKEND_FLAG.parent.mkdir(parents=True, exist_ok=True)
    temp = BACKEND_FLAG.with_suffix('.tmp')
    temp.write_text(json.dumps({'enabled': enabled}), encoding='utf-8')
    temp.replace(BACKEND_FLAG)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['on', 'off', 'shadow'])
    args = parser.parse_args()
    if args.mode == 'on':
        check_ready()
        backend_mode(True)
        try:
            host_mode('on')
        except Exception:
            backend_mode(False)
            raise
    else:
        host_mode('off')
        backend_mode(False)
    print('department mode:', args.mode)


if __name__ == '__main__':
    main()
