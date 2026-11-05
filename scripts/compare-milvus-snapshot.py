"""Read-only sampled parity check for frozen migration collections."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'data/milvus-sdk'))
import httpx
from pymilvus import MilvusClient

report_file=ROOT/'data/manuals/runtime/milvus-migration/snapshot-20261105_100424.json'
report=json.loads(report_file.read_text(encoding='utf-8'))
target=MilvusClient(uri='http://127.0.0.1:19530',timeout=60)
with httpx.Client(timeout=30,trust_env=False) as source:
 for name,info in report['collections'].items():
  res=source.post(f'http://127.0.0.1:6333/collections/{name}/points/scroll',json={'limit':8,'with_vector':True,'with_payload':True}).json()
  scores={'dense':[],'sparse':[]}
  for point in res['result']['points']:
   for kind in scores:
    vector=point['vector'][kind]
    qbody={'using':kind,'query':vector,'limit':10,'with_payload':False,'filter':{'must':[{'key':'chunk_level','match':{'value':'child'}}]}}
    original=source.post(f'http://127.0.0.1:6333/collections/{name}/points/query',json=qbody).json()['result']['points']
    query=vector if kind=='dense' else dict(zip(vector['indices'],vector['values']))
    result=target.search(collection_name=info['destination'],data=[query],anns_field=kind,limit=10,
     filter='payload["chunk_level"] == "child"',search_params={'metric_type':'COSINE' if kind=='dense' else 'IP'},output_fields=['id'])
    old=[str(p['id']) for p in original];new=[str(p['id']) for p in result[0]]
    scores[kind].append({'overlap':len(set(old)&set(new)),'top1_equal':old[:1]==new[:1]})
  info['retrieval_parity']={k:{'queries':len(v),'mean_top10_overlap':sum(x['overlap'] for x in v)/len(v),
   'top1_equal_count':sum(x['top1_equal'] for x in v)} for k,v in scores.items()}
report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v['retrieval_parity'] for k,v in report['collections'].items()},ensure_ascii=False))
