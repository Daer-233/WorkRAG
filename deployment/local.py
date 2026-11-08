"""Start, stop, or inspect only this deployment's services."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import psutil
from dotenv import load_dotenv,dotenv_values

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT/'data/manuals/runtime/local'
DOCKER = Path('G:/docker/Desktop/resources/bin/docker.exe')
COMPOSE = ['-f','G:/docker/workrag/compose.yaml']
SERVICES = [('embedding',8031,'embedding_app.main:app','apps/embedding'),
            ('rerank',8032,'rerank_app.main:app','apps/rerank'),
            ('backend',8060,'app.manual_main:app','apps/backend'),
            ('workrag-mcp',8061,'workrag_agent.mcp_server:app','apps/workrag-agent')]

def docker(*args):
    subprocess.run([str(DOCKER),'compose',*COMPOSE,*args],check=True)

def process(name):
    file = RUNTIME/f'{name}.json'
    if not file.exists(): return None
    record = json.loads(file.read_text())
    try:
        p = psutil.Process(record['pid'])
        if abs(p.create_time()-record['created']) > 1: return None
        if not any(module in ' '.join(p.cmdline()) for _,_,module,_ in SERVICES):
            raise RuntimeError('Recorded process does not belong to WorkRAG')
        return p
    except psutil.NoSuchProcess:
        return None

def status():
    try:
        r=httpx.get('http://127.0.0.1:8062/health',timeout=5,trust_env=False)
        print('pi-harness',r.status_code,r.text)
    except httpx.HTTPError as e: print('pi-harness','unavailable',type(e).__name__)
    for name,port,_,_ in SERVICES:
        try:
            r=httpx.get(f'http://127.0.0.1:{port}/health',timeout=10,trust_env=False)
            print(name,r.status_code,r.text)
        except Exception as e: print(name,'unavailable',type(e).__name__)
    if DOCKER.exists(): docker('ps')

def start():
    from pi_harness_service import start as start_pi
    start_pi()
    RUNTIME.mkdir(parents=True,exist_ok=True)
    for name,port,_,_ in SERVICES:
        if process(name): continue
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',port))==0:
                raise RuntimeError(f'Port {port} is occupied by an untracked service')
    docker('up','-d','--wait','--wait-timeout','300')
    from ensure_native_file_output import ensure
    from install_dingtalk_a2ui_bridge import restore
    from install_legacy_media_bridge import restore as restore_media
    file_changed=ensure()
    a2ui_changed=restore()
    media_changed=restore_media()
    if file_changed or a2ui_changed or media_changed:
        docker('restart','langbot')
    load_dotenv(ROOT/'instances/manuals/.env',override=True)
    load_dotenv(ROOT/'data/manuals/runtime/agent.env',override=True)
    os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
    os.environ['OMP_NUM_THREADS']='4'
    os.environ['MKL_NUM_THREADS']='4'
    os.environ['PYTHONIOENCODING']='utf-8'
    subprocess.run([sys.executable,str(ROOT/'scripts/manual-instance.py'),'init'],cwd=ROOT,check=True)
    for name,port,module,appdir in SERVICES:
        if process(name): continue
        with (RUNTIME/f'{name}.log').open('ab') as log:
            p=subprocess.Popen([sys.executable,'-m','uvicorn',module,'--app-dir',str(ROOT/appdir),
                                '--host','127.0.0.1','--port',str(port)],cwd=ROOT,stdout=log,stderr=log,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        (RUNTIME/f'{name}.json').write_text(json.dumps({'pid':p.pid,'created':psutil.Process(p.pid).create_time()}))
    for _ in range(60):
        try:
            for _,port,_,_ in SERVICES:
                httpx.get(f'http://127.0.0.1:{port}/health',timeout=3,trust_env=False).raise_for_status()
            break
        except httpx.HTTPError: time.sleep(2)
    else: raise RuntimeError(f'Services did not become healthy; inspect {RUNTIME}')
    for port,path,payload in [(8031,'/embed',{'texts':['WorkRAG startup readiness']}),
                              (8032,'/rerank',{'query':'启动验收','documents':['服务启动验收']})]:
        if httpx.get(f'http://127.0.0.1:{port}/health',trust_env=False,timeout=5).json().get('status')!='ok':
            print('Warming CPU model on port',port,flush=True)
            httpx.post(f'http://127.0.0.1:{port}'+path,json=payload,trust_env=False,timeout=180).raise_for_status()
    wait_agent_ready()
    status()


def wait_agent_ready():
    keyfile=ROOT/'data/manuals/runtime/langbot-integration/.env'
    if not keyfile.exists(): return
    key=dotenv_values(keyfile).get('LANGBOT_API_KEY')
    if not key: return
    for _ in range(90):
        try:
            r=httpx.get('http://127.0.0.1:5300/api/v1/plugins',headers={'X-API-Key':key},timeout=5,trust_env=False)
            r.raise_for_status()
            plugins=r.json()['data']['plugins']
            matches=[p for p in plugins if p.get('manifest',{}).get('manifest',{}).get('metadata',{}).get('name')=='WorkRAGGraph']
            if not matches:return
            if matches[0].get('enabled') and matches[0].get('status')=='initialized':break
            if matches[0].get('enabled') is False:return
        except (httpx.HTTPError,KeyError,ValueError):pass
        time.sleep(2)
    else:raise RuntimeError('WorkRAG plugin did not initialize; inspect LangBot plugin status')
    # Recreate the MCP connection after plugins finish loading. The Host may
    # advertise a connected catalog while retaining an obsolete transport.
    with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':key},trust_env=False,timeout=30) as client:
        servers=client.get('/api/v1/mcp/servers');servers.raise_for_status()
        from entry_names import resolve_mcp_server
        server=resolve_mcp_server(servers.json()['data']['servers'])
        if not server:return
        from urllib.parse import quote
        server_path='/api/v1/mcp/servers/'+quote(server['name'],safe='')
        response=client.get(server_path);response.raise_for_status()
        server=response.json()['data']['server']
        response=client.put(server_path,json={k:server[k] for k in ('name','mode','enable','extra_args')})
        response.raise_for_status()
        for _ in range(60):
            catalog=client.get('/api/v1/agents/_/metadata');catalog.raise_for_status()
            if len([t for t in catalog.json()['data']['host_tools'] if t.get('source_id')==server['uuid']])==4:return
            time.sleep(1)
    raise RuntimeError('WorkRAG MCP tools did not become ready')

def stop():
    from pi_harness_service import stop as stop_pi
    stop_pi()
    for name,_,_,_ in reversed(SERVICES):
        p=process(name)
        if p:
            owned=p.children(recursive=True)+[p]
            for child in owned:
                try: child.terminate()
                except psutil.NoSuchProcess: pass
            _,alive=psutil.wait_procs(owned,timeout=15)
            for child in alive:
                try: child.kill()
                except psutil.NoSuchProcess: pass
    docker('stop')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['start','stop','status'])
    action=parser.parse_args().action
    {'start':start,'stop':stop,'status':status}[action]()
