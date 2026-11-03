"""Refresh only this Pipeline's stale desktop Codex executable path."""
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import httpx

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('connection',ROOT/'scripts/connect-langbot-knowledge.py')
conn=importlib.util.module_from_spec(spec);spec.loader.exec_module(conn)


def main():
    base=Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin'
    candidates=sorted(base.glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not candidates: raise RuntimeError('Installed desktop Codex executable not found')
    current=candidates[0].resolve()
    assert current.is_relative_to(base.resolve())
    subprocess.run([str(current),'--version'],check=True,capture_output=True,timeout=15)
    with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':conn.credential()},timeout=30) as client:
        before=conn.data(client.get(f'/api/v1/pipelines/{conn.PIPELINE}'))['pipeline']['config']
        config=deepcopy(before)
        settings=config['ai']['runner_config'][conn.RUNNER]
        old=settings['command']
        if Path(old).is_file():
            print('Configured executable exists; no change.')
            return
        if not Path(old).is_relative_to(base):
            raise RuntimeError('Configured executable is not a stale desktop Codex path; review required')
        backup=ROOT/'data/manuals/runtime'/('codex-command-before-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.private.json')
        backup.write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
        settings['command']=current.as_posix()
        conn.data(client.put(f'/api/v1/pipelines/{conn.PIPELINE}',json={'config':config}))
        after=conn.data(client.get(f'/api/v1/pipelines/{conn.PIPELINE}'))['pipeline']['config']
        assert after==config
        after=deepcopy(after);after['ai']['runner_config'][conn.RUNNER]['command']=old
        assert after==before
    print('Updated only the stale Codex executable setting; model, permissions and knowledge bindings preserved.')


if __name__=='__main__':main()
