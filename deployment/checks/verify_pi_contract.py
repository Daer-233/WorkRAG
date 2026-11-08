"""Run Pi/SDK contract tests in the installed plugin runtime without real provider I/O."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
import subprocess
from uuid import uuid4
from install_agent import DOCKER,ROOT
from pi_harness_service import start,config

start()
target='/tmp/workrag-pi-check-'+uuid4().hex
subprocess.run([DOCKER,'cp',str(ROOT/'apps/workrag-agent'),'workrag-langbot_plugin_runtime-1:'+target],check=True)
for name in ('sdk_model_check.py','sdk_pi_check.py'):
    subprocess.run([DOCKER,'exec','-i','-e','PYTHONPATH='+target,'workrag-langbot_plugin_runtime-1',
                    '/app/.venv/bin/python',target+'/tests/'+name],check=True,
                   input=json.dumps({'url':'ws://host.docker.internal:8062/run','token':config()['token']}),text=True)
