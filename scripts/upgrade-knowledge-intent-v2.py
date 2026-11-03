"""Activate the factor schema in shadow only; leave answers and models alone."""
import json
from pathlib import Path
import subprocess
import sys
import os

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
from dotenv import load_dotenv
load_dotenv(ROOT/'instances/manuals/.env',override=True)
from app.manuals.intent.settings import CONFIG,calibration_valid,config


def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)


def main():
    previous=json.loads(CONFIG.read_text(encoding='utf-8')) if CONFIG.exists() else {}
    backup=ROOT/'data/manuals/runtime/intent-v2-before.private.json'
    if not backup.exists():atomic(backup,previous)
    selected=config();selected.update(mode='shadow',version='intent-v2-factors',sample_set='v2',terra_enabled=True)
    atomic(CONFIG,selected)
    if not calibration_valid(selected):
        atomic(CONFIG,previous)
        raise RuntimeError('V2 frozen calibration does not match the installed source; configuration restored')
    subprocess.run([sys.executable,str(ROOT/'scripts/set-knowledge-intent-mode.py'),'shadow'],check=True)
    print('Configured intent-v2-factors in shadow. Reload backend only; answer model/runner/template unchanged.')


if __name__=='__main__':main()
