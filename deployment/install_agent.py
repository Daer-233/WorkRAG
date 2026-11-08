"""Stage/build/install the local plugin through LangBot's official interfaces."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import time
import sys
from uuid import uuid4

import httpx
import yaml
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'data/manuals/runtime/agent-deployment'
DOCKER='G:/docker/Desktop/resources/bin/docker.exe'
CONFIG='G:/docker/workrag/compose.yaml'
def docker(*args): return subprocess.check_output([DOCKER,*args],text=True,encoding='utf-8',errors='replace')

def client():
    cfg=dotenv_values(ROOT/'data/manuals/runtime/langbot-integration/.env')
    return httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':cfg['LANGBOT_API_KEY']},timeout=210,trust_env=False)

def data(r):
    if r.status_code>=400: raise RuntimeError('LangBot HTTP '+str(r.status_code)+': '+r.text[:1200])
    d=r.json()
    if d.get('code',0)!=0: raise RuntimeError(str(d)[:1200])
    return d.get('data',{})

def prepare():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    subprocess.run([sys.executable,str(ROOT/'deployment/provision_agent.py')],check=True,cwd=ROOT)

def build():
    stage=RUNTIME/('build-'+uuid4().hex)
    shutil.copytree(ROOT/'plugins/WorkRAGGraph',stage,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT/'apps/workrag-agent/workrag_agent',stage/'workrag_agent',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (stage/'requirements.txt').write_text('langbot-plugin==0.7.16\n'+(ROOT/'apps/workrag-agent/requirements.txt').read_text(),encoding='utf-8')
    target='/tmp/'+stage.name
    docker('cp',str(stage),'workrag-langbot_plugin_runtime-1:'+target)
    print(docker('exec','-w',target,'workrag-langbot_plugin_runtime-1','/app/.venv/bin/python','-m','langbot_plugin.cli.__init__','build','--output','dist'))
    version=yaml.safe_load((stage/'manifest.yaml').read_text(encoding='utf-8'))['metadata']['version']
    output=RUNTIME/f'workrag-WorkRAGGraph-{version}.lbpkg'
    docker('cp','workrag-langbot_plugin_runtime-1:'+target+'/dist/'+output.name,str(output))
    return output

def install(output):
    with client() as c:
        with output.open('rb') as file: result=data(c.post('/api/v1/plugins/install/local',files={'file':(output.name,file,'application/zip')}))
    (RUNTIME/'installation-task.json').write_text(json.dumps(result),encoding='utf-8')
    print('Plugin installation task:',result)
    with client() as c:
        for _ in range(180):
            status=data(c.get('/api/v1/system/tasks/'+str(result['task_id'])))
            if status['status']=='succeeded': break
            if status['status'] not in ('pending','running','queued'):
                raise RuntimeError('Plugin installation failed: '+str(status.get('error'))[:500])
            time.sleep(1)
        else: raise TimeoutError('Plugin installation did not complete')
        # Plugin catalog refresh in v4.11.3 can clear the MCP tools cache while
        # retaining connected status. Reconnect this server using the official API.
        import local
        local.wait_agent_ready()
        print('Plugin installed successfully')

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['prepare','build','install','all']); args=parser.parse_args()
    if args.action in ('prepare','all'): prepare()
    version=yaml.safe_load((ROOT/'plugins/WorkRAGGraph/manifest.yaml').read_text(encoding='utf-8'))['metadata']['version']
    output=build() if args.action in ('build','all') else RUNTIME/f'workrag-WorkRAGGraph-{version}.lbpkg'
    if args.action in ('install','all'): install(output)
