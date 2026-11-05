"""Send the initial status with the DingTalk card's first delivery."""
import argparse
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'data/manuals/runtime'
TARGET = '/app/src/langbot/libs/dingtalk_api/api.py'
BACKUP = RUNTIME / 'dingtalk-api.before-initial-card.py'

OLD = """            'content': '',
            'answer': '',
            'reasoning': '',
            'flowStatus': '1',
"""
NEW = """            'content': '正在处理',
            'answer': '正在处理',
            'reasoning': '',
            'flowStatus': '2',
"""


def docker(*args):
    subprocess.run(['docker', *args], check=True, timeout=40)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if args.rollback:
        docker('cp', str(BACKUP), f'langbot:{TARGET}')
        return
    RUNTIME.mkdir(parents=True, exist_ok=True)
    current = RUNTIME / 'dingtalk-api.initial-card.py'
    docker('cp', f'langbot:{TARGET}', str(current))
    source = current.read_text(encoding='utf-8')
    before, create, after = source.partition('    async def create_and_card(')
    body, next_method, rest = after.partition('    async def send_card_message(')
    if not (create and next_method):
        raise SystemExit('Unexpected DingTalk chat card implementation.')
    if body.count(NEW) == 1:
        return
    if body.count(OLD) != 1:
        raise SystemExit('Unexpected DingTalk chat card parameters.')
    patched = before + create + body.replace(OLD, NEW) + next_method + rest
    compile(patched, TARGET, 'exec')
    # Refresh the backup from the active version after image updates.
    BACKUP.write_bytes(current.read_bytes())
    current.write_text(patched, encoding='utf-8')
    docker('cp', str(current), f'langbot:{TARGET}')
    print('Restart LangBot to send the initial status with the card.')


if __name__ == '__main__':
    main()
