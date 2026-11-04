"""Shadow-only deployment of the sealed task-trained classifier.

Does not touch LangBot answer-model/runner settings, corpora or vector stores.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
from dotenv import load_dotenv
load_dotenv(ROOT/'instances/manuals/.env',override=True)
from app.manuals.intent.settings import CONFIG,DATA,calibration_valid,config
from app.manuals.intent.supervised import verify_manifest

def main():
 model=DATA/'models/intent/supervised-bert-v3';verify_manifest(model)
 old=config();candidate={**old,'mode':'shadow','version':'intent-v3-supervised','sample_set':'v3','model_path':str(model),'terra_enabled':True}
 artifact=calibration_valid(candidate)
 if not artifact or not artifact.get('supervised_validated'):raise RuntimeError('Sealed V3 calibration is missing or changed')
 backup=DATA/'runtime/intent-v3-before.private.json'
 if not backup.exists():backup.write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
 # Force Host shadow before changing backend version. No actual answer changes.
 spec=importlib.util.spec_from_file_location('switch',ROOT/'scripts/set-knowledge-intent-mode.py')
 switch=importlib.util.module_from_spec(spec);spec.loader.exec_module(switch)
 bridge=DATA/'runtime/intent-host-v3.json';switch.atomic(bridge,{'mode':'shadow','version':candidate['version']})
 subprocess.run(['docker','cp',str(bridge),'langbot:/app/data/work-knowledge-intent.pending.json'],check=True,capture_output=True)
 subprocess.run(['docker','exec','langbot','mv','/app/data/work-knowledge-intent.pending.json','/app/data/work-knowledge-intent.json'],check=True,capture_output=True)
 switch.atomic(CONFIG,candidate)
 print(json.dumps({'mode':'shadow','version':candidate['version'],'terra_enabled':True,'answer_pipeline':'unchanged'}))

if __name__=='__main__':main()
