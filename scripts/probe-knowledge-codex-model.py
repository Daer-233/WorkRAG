"""Read account model catalog and resolve fresh/resumed thread model; no turns."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'data/manuals/runtime/langbot-codex'
TARGET='gpt-6-luna'
ARGS=['-c','model="gpt-6-luna"','-c','model_reasoning_effort="high"']


async def main():
    sys.path[:0]=[str(RUNTIME/'sdk'),str(RUNTIME/'official-plugin')]
    from pkg.native_cli import _CodexAppServerClient
    from knowledge_codex_model import install
    install(_CodexAppServerClient)
    candidates=list((Path.home()/'AppData/Local/OpenAI/Codex/bin').glob('*/codex.exe'))
    command=max(candidates,key=lambda p:p.stat().st_mtime)
    sessions=sorted(list((RUNTIME/'workspace/.langbot-codex-home').rglob('sessions/**/*.jsonl')),
        key=lambda p:p.stat().st_mtime,reverse=True)
    # Resume in the same isolated Codex home that owns the saved thread. A
    # rollout owned by another home's state database cannot be resumed there.
    home=next((p.parent for p in sessions[0].parents if p.name=='sessions'),RUNTIME/'codex-auth-home') if sessions else RUNTIME/'codex-auth-home'
    env={**os.environ,'CODEX_HOME':str(home)}
    process=await asyncio.create_subprocess_exec(str(command),'app-server','--listen','stdio://',*ARGS,
        cwd=RUNTIME/'workspace',env=env,stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=16*1024*1024)
    client=_CodexAppServerClient(process,streaming=True,approval_grant=None,approval_policy='on-request')
    reader=asyncio.create_task(client.read_stdout())
    report={}
    try:
        async with asyncio.timeout(45):
            await client.initialize()
            catalog=await client.request('model/list',{'limit':100,'includeHidden':True})
            rows=catalog.get('data',[])
            row=next((r for r in rows if r.get('id')==TARGET or r.get('model')==TARGET),None)
            report['target_listed']=row is not None
            if row:
                report['default_effort']=row.get('defaultReasoningEffort')
                report['supported_efforts']=row.get('supportedReasoningEfforts')
            fresh=await client.request('thread/start',{'cwd':str(RUNTIME/'workspace'),
                'approvalPolicy':'on-request','sandbox':'read-only','model':None,'ephemeral':True})
            report['fresh_model']=fresh.get('model')
            report['fresh_reasoning_effort']=fresh.get('reasoningEffort')
            # Read only this assistant's latest saved session. No turn, user
            # message, tool call, transcript deletion or platform delivery.
            if sessions:
                meta=json.loads(sessions[0].open(encoding='utf-8').readline())
                thread=meta.get('payload',{}).get('id')
                if thread:
                    resumed=await client.request('thread/resume',{'threadId':thread,'cwd':str(RUNTIME/'workspace'),
                        'approvalPolicy':'on-request','sandbox':'read-only','model':None})
                    report['resumed_model']=resumed.get('model')
                    report['resumed_reasoning_effort']=resumed.get('reasoningEffort')
            report['resolved_target']=report.get('fresh_model')==TARGET and report.get('resumed_model',TARGET)==TARGET
            out=ROOT/'output/model-migration-luna-20261103'
            out.mkdir(parents=True,exist_ok=True)
            (out/'model-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report))
    finally:
        if process.returncode is None:
            process.terminate()
        with contextlib.suppress(Exception): await asyncio.wait_for(process.wait(),5)
        reader.cancel()
        await asyncio.gather(reader,return_exceptions=True)


if __name__=='__main__':asyncio.run(main())
