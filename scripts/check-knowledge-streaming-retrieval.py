"""One local read-only retrieval after shared services are ready."""
import json
from pathlib import Path
import time
import httpx

start=time.monotonic()
with httpx.Client(timeout=180,headers={'X-Manual-Request':'1'}) as client:
    response=client.post('http://127.0.0.1:8060/api/v1/manuals/retrieve',json={
        'query':'每月补卡次数和申请时限','top_k':3})
    response.raise_for_status()
    data=response.json()
results=data.get('results',[])
report={'status':data.get('status'),'elapsed_seconds':round(time.monotonic()-start,2),
    'source_count':sum(r.get('metadata',{}).get('result_type')=='source_evidence' for r in results),
    'has_onboarding':any('LSD新员工入职培训' in r.get('metadata',{}).get('title','') for r in results),
    'has_original_page_6':any(step.get('source',{}).get('page')==6 for r in results for step in r.get('metadata',{}).get('steps',[]))}
out=Path(__file__).resolve().parents[1]/'output/knowledge-card-v1/retrieval-verification.json'
out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report))
