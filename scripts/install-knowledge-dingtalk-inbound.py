"""Install or restore the local DingTalk Stream receiver."""
import argparse
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
TARGET = '/app/src/langbot/libs/dingtalk_api/EchoHandler.py'
BACKUP = ROOT / 'data/manuals/runtime/dingtalk-echo-handler.before.py'


def docker(*args):
    subprocess.run(['docker', *args], check=True, timeout=40)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if args.rollback:
        docker('cp', str(BACKUP), f'langbot:{TARGET}')
    else:
        source = ROOT / 'scripts/knowledge_dingtalk_inbound.py'
        compile(source.read_text(encoding='utf-8'), str(source), 'exec')
        docker('exec', '-e', 'PYTHONPATH=/app/src', 'langbot', '/app/.venv/bin/python', '-c',
               'from langbot.libs.dingtalk_api.api import DingTalkClient; '
               'assert callable(DingTalkClient._start_inbound_task)')
        BACKUP.parent.mkdir(parents=True, exist_ok=True)
        if not BACKUP.exists():
            docker('cp', f'langbot:{TARGET}', str(BACKUP))
        docker('cp', str(source), f'langbot:{TARGET}')
    print('Restart LangBot to load the receiver.')


if __name__ == '__main__':
    main()
