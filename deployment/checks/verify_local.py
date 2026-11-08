"""Idempotent deployment smoke test using explicitly synthetic material."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
from pathlib import Path
import subprocess
import time
import httpx

ROOT=Path(__file__).resolve().parents[2]
REPORT=ROOT/'data/manuals/runtime/acceptance.json'
TITLE='部署验收示例（非真实业务制度）'
QUESTION='部署验收示例的测试编号是什么？'
MARKER='WRAG-LOCAL-20261107'
client=httpx.Client(base_url='http://127.0.0.1:8060',headers={'X-Manual-Request':'1'},timeout=360,trust_env=False)
def call(method,path,**kwargs):
    r=client.request(method,path,**kwargs); r.raise_for_status(); return r.json()

report={'source_commit':(ROOT/'data/manuals/runtime/source-commit.txt').read_text().strip()}
for name,port,payload,path in [
    ('embedding',8031,{'texts':['本地部署验收：知识库测试编号。']},'/embed'),
    ('rerank',8032,{'query':'部署验收编号','documents':['部署验收编号是 '+MARKER,'这是一份天气说明。']},'/rerank')]:
    r=httpx.post(f'http://127.0.0.1:{port}{path}',json=payload,timeout=360,trust_env=False)
    r.raise_for_status(); result=r.json()
    if name=='embedding':
        assert result['dense_dimension']==1024 and len(result['dense_vectors'][0])==1024
        assert result['sparse_vectors'][0]['indices']
    else:
        scores={item['index']:item['score'] for item in result['results']}
        assert scores[0]>scores[1]
    report[name]={'real_inference':True,'model_id':result['model_id']}

entries=call('GET','/api/v1/manuals/entries')
entry=next((e for e in entries if e['title']==TITLE),None)
if entry is None:
    entry=call('POST','/api/v1/manuals/entries',json={'title':TITLE,'version':'local-smoke-v1'})
eid=entry['id']
if entry['status']=='draft':
    from docx import Document
    fixture=ROOT/'data/manuals/runtime/deployment-smoke.docx'
    document=Document()
    document.add_heading(TITLE,0)
    for line in ['此文档仅用于软件验收，不代表公司制度。','1. 打开本机 WorkRAG 管理页。',f'2. 部署验收测试编号为 {MARKER}。','3. 核对检索结果中的来源标题。']:
        document.add_paragraph(line)
    document.save(fixture)
    with fixture.open('rb') as f:
        call('POST',f'/api/v1/manuals/entries/{eid}/files',files={'file':(fixture.name,f,'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    call('POST',f'/api/v1/manuals/entries/{eid}/parse-local')
    entry=call('GET',f'/api/v1/manuals/entries/{eid}')
    steps=[{k:v for k,v in s.items() if k in {'order','title','instruction','asset_ids','section_asset_ids','page'}} for s in entry['steps']]
    groups=entry.get('groups') or [{'id':'smoke','title':TITLE,'start':0,'end':len(steps),'confirmed':True}]
    groups=[{k:v for k,v in g.items() if k in {'id','title','start','end','confirmed'}} for g in groups]
    for g in groups: g['confirmed']=True
    call('PUT',f'/api/v1/manuals/entries/{eid}/steps',json={'steps':steps,'groups':groups})
    call('POST',f'/api/v1/manuals/entries/{eid}/publish')
for _ in range(180):
    entry=call('GET',f'/api/v1/manuals/entries/{eid}')
    if entry['index_status']=='indexed': break
    if entry['index_status']=='failed': raise RuntimeError('Example indexing failed: '+str(entry.get('error_message')))
    time.sleep(2)
else: raise TimeoutError('Example indexing did not finish')
payload={'query':QUESTION,'top_k':5,'filters':{'entry_id':eid}}
result=call('POST','/api/v1/manuals/retrieve',json=payload)
assert MARKER in json.dumps(result,ensure_ascii=False),result
assert result['status']=='ok'
metrics=result.get('retrieval_metrics',{})
assert all(metrics.get(key,0)>0 for key in ['dense_count','sparse_count','keyword_count','rerank_input_count','returned_evidence_count']),metrics
report['sample']={'entry_id':eid,'title':TITLE,'retrieval':result}
docker='G:/docker/Desktop/resources/bin/docker.exe'
probe="import urllib.request,json; req=urllib.request.Request('http://host.docker.internal:8060/api/v1/manuals/retrieve',data="+repr(json.dumps(payload).encode())+",headers={'Content-Type':'application/json','X-Manual-Request':'1','Host':'localhost:8060'}); result=json.load(urllib.request.urlopen(req,timeout=360)); assert '"+MARKER+"' in json.dumps(result); print('LangBot container retrieval OK')"
subprocess.run([docker,'compose','-f','G:/docker/workrag/compose.yaml','exec','-T','langbot','python','-c',probe],check=True)
report['langbot_container_retrieval']=True
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('Synthetic document published, indexed, retrieved; report:',REPORT)
