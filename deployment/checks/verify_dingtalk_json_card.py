"""Validate card assets with the official Python and native DWS validators."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from install_agent import ROOT,RUNTIME

def verify():
    out=RUNTIME/'card-json-v2';refs=RUNTIME/'card-json-reference'
    source=refs/'official-dingtalk-aicard/skills/dingtalk-aicard'
    validator=source/'scripts/aicard_lint.py';dws=refs/'dws-tool/dws.exe'
    checks=[]
    def run(name,args):
        result=subprocess.run([str(a) for a in args],capture_output=True,text=True,encoding='utf-8')
        if result.returncode:raise RuntimeError(name+': '+result.stdout[:1500]+result.stderr[:500])
        report=json.loads(result.stdout);data=report.get('data',report)
        if data.get('valid') is not True or data.get('preflight',{}).get('valid') is not True:
            raise RuntimeError(name+': validation did not pass')
        checks.append({'name':name,'result':report})
    for file in sorted(out.glob('*.a2ui.json')):
        mode='new-card' if file.name=='workrag-card.a2ui.json' else 'resources'
        run('official-python:'+file.name,[sys.executable,validator,file,'--preflight',mode,'--format','json'])
    card=out/'workrag-card.a2ui.json'
    for mode in ['new-card','resources']:
        run('official-dws:'+mode,[dws,'aicard','lint','--file',card,'--preflight',mode])
    tree=json.loads((refs/'official-tree.json').read_text(encoding='utf-8'))
    report={'official_repository':'https://github.com/DingTalk-Real-AI/dingtalk-aicard',
            'official_repository_commit':tree['sha'],'dws_version':'1.0.67','valid':True,
            'renderingVerified':False,'checks':checks,'sent_to_dingtalk':False,'bot_binding_changed':False}
    (out/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    status=json.loads((out/'status.json').read_text(encoding='utf-8'))
    status.update(official_lint_verified=True,official_python_verified=True,official_repository_commit=tree['sha'])
    (out/'status.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'README.md').write_text((ROOT/'docs/history/cards/钉钉JSON卡片V2说明.md').read_text(encoding='utf-8'),encoding='utf-8')
    package=out/'WorkRAG-钉钉卡片V2.zip'
    with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as bundle:
        for file in sorted(out.rglob('*')):
            if file.is_file() and file!=package:bundle.write(file,file.relative_to(out))
    print('PASS',len(checks),'official validation checks; package prepared; no message sent')

if __name__=='__main__':verify()
