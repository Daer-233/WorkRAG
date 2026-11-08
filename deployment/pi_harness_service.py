"""Manage the loopback-only Node Pi worker under the existing G-drive setup."""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import psutil
import httpx
from install_agent import ROOT,RUNTIME

RECORD=RUNTIME/'pi-harness-process.json';PRIVATE=RUNTIME/'pi-harness.private.json'

def config():
    if not PRIVATE.exists():PRIVATE.write_text(json.dumps({'token':secrets.token_urlsafe(48)}),encoding='utf-8')
    return json.loads(PRIVATE.read_text())

def process():
    if not RECORD.exists():return None
    row=json.loads(RECORD.read_text())
    try:
        p=psutil.Process(row['pid'])
        if abs(p.create_time()-row['created'])>1:return None
        if not any('pi-harness' in a and 'server.mjs' in a for a in p.cmdline()):raise RuntimeError('Pi PID ownership mismatch')
        return p
    except psutil.NoSuchProcess:return None

def start():
    if process():return
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',8062))==0:raise RuntimeError('Port 8062 already occupied')
    node=shutil.which('node.exe') or shutil.which('node')
    if not node:raise RuntimeError('Node >=22.19 is required')
    env={**os.environ,'PI_HARNESS_TOKEN':config()['token']}
    with (RUNTIME/'pi-harness.log').open('ab') as log:
        p=subprocess.Popen([node,str(ROOT/'apps/pi-harness/server.mjs')],cwd=ROOT/'apps/pi-harness',env=env,
                           stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    RECORD.write_text(json.dumps({'pid':p.pid,'created':psutil.Process(p.pid).create_time()}))
    import time
    for _ in range(30):
        try:httpx.get('http://127.0.0.1:8062/health',trust_env=False,timeout=2).raise_for_status();return
        except httpx.HTTPError:time.sleep(.2)
    raise RuntimeError('Pi worker startup failed; inspect pi-harness.log')

def stop():
    p=process()
    if p:p.terminate();p.wait(10)

if __name__=='__main__':{'start':start,'stop':stop}[sys.argv[1]]()
