"""Immediately reversible off / shadow / gated on. No corpus/index mutations."""
import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
from dotenv import load_dotenv
load_dotenv(ROOT/'instances/manuals/.env',override=True)
from app.manuals.intent.settings import CONFIG,activation_valid,config,report_dir


def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['off','shadow','on']);p.add_argument('--pin-answer-model',action='store_true');args=p.parse_args()
    cfg=config();cfg['mode']=args.mode
    if args.mode=='on' and not activation_valid(cfg):raise SystemExit('Activation gates not met; keep shadow. See '+str(report_dir(cfg)/'acceptance.json'))
    bridge={'mode':args.mode,'version':cfg['version']}
    runtime=ROOT/'data/manuals/runtime';runtime.mkdir(parents=True,exist_ok=True)
    file=runtime/'intent-host.json';atomic(file,bridge)
    def deploy():
        subprocess.run(['docker','cp',str(file),'langbot:/app/data/work-knowledge-intent.pending.json'],check=True,capture_output=True)
        subprocess.run(['docker','exec','langbot','mv','/app/data/work-knowledge-intent.pending.json','/app/data/work-knowledge-intent.json'],check=True,capture_output=True)
    # Disable Host enforcement first on rollback; enable it last on activation.
    if args.mode=='off':deploy();atomic(CONFIG,cfg)
    else:atomic(CONFIG,cfg);deploy()
    if args.pin_answer_model:
        spec=importlib.util.spec_from_file_location('connection',ROOT/'scripts/connect-langbot-knowledge.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        import httpx
        with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':module.credential()},timeout=30,trust_env=False) as client:
            before=module.data(client.get('/api/v1/pipelines/'+module.PIPELINE))['pipeline']['config']
            after=deepcopy(before);settings=after['ai']['runner_config'][module.RUNNER]
            current=json.loads(settings.get('args-json') or '[]')
            selected=['-c','model="gpt-6.1-terra"','-c','model_reasoning_effort="medium"']
            # Preserve unrelated native CLI args, but do not stack competing model overrides.
            kept=[];i=0
            while i<len(current):
                if current[i] in ('-c','--config') and i+1<len(current) and current[i+1].split('=',1)[0] in ('model','model_reasoning_effort'):i+=2
                elif current[i] in ('-m','--model') and i+1<len(current):i+=2
                else:kept.append(current[i]);i+=1
            settings['args-json']=json.dumps(kept+selected)
            atomic(runtime/'intent-model-before.private.json',{'config':before}) if not (runtime/'intent-model-before.private.json').exists() else None
            module.data(client.put('/api/v1/pipelines/'+module.PIPELINE,json={'config':after}))
            saved=module.data(client.get('/api/v1/pipelines/'+module.PIPELINE))['pipeline']['config']
            if saved!=after:raise RuntimeError('Model config verification failed')
    print(json.dumps({'mode':args.mode,'version':cfg['version'],'answer_model':'gpt-6.1-terra/medium' if args.pin_answer_model else 'unchanged'}))


if __name__=='__main__':main()
