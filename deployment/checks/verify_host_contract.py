"""Checks against the actual installed Host authorization code and plugin SDK."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import subprocess
from uuid import uuid4
from install_agent import DOCKER,ROOT,RUNTIME

code="""
from pathlib import Path
from types import SimpleNamespace
from langbot.pkg.api.http.authz import permissions_for_role,Permission,require_permission,PermissionDeniedError
source=Path('/app/src/langbot/pkg/api/http/controller/groups/plugins.py').read_text()
offset=source.index('/page-api')
assert 'permission=Permission.RESOURCE_MANAGE' in source[offset:offset+230]
for role in ('viewer','operator'):
    ctx=SimpleNamespace(workspace=SimpleNamespace(permissions=permissions_for_role(role)))
    try:require_permission(ctx,Permission.RESOURCE_MANAGE)
    except PermissionDeniedError:pass
    else:raise AssertionError(role+' could review')
for role in ('developer','admin','owner'):
    ctx=SimpleNamespace(workspace=SimpleNamespace(permissions=permissions_for_role(role)))
    require_permission(ctx,Permission.RESOURCE_MANAGE)
print('PASS Host Page guard rejects viewer/operator; permits resource managers')
"""
subprocess.run([DOCKER,'exec','-e','PYTHONPATH=/app/src','workrag-langbot-1','/app/.venv/bin/python','-c',code],check=True)
target='/tmp/workrag-sdk-'+uuid4().hex
subprocess.run([DOCKER,'cp',str(ROOT/'apps/workrag-agent'),'workrag-langbot_plugin_runtime-1:'+target],check=True)
subprocess.run([DOCKER,'exec','-e','PYTHONPATH='+target,'workrag-langbot_plugin_runtime-1',
                '/app/.venv/bin/python',target+'/tests/sdk_model_check.py'],check=True)
