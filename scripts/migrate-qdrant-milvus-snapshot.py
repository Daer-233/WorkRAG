"""Copy vector snapshots into new Milvus collections; never alter source.

This is a staging snapshot, not an application cutover. Re-run requires new
collection names; a live source can change while copying, which is detected
but cannot be treated as an atomic snapshot.
"""
import hashlib
import argparse
import json
from pathlib import Path
import sys
import time
from datetime import datetime
from uuid import UUID
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'data/milvus-sdk'))
import httpx
from pymilvus import MilvusClient,DataType

def canonical(point):
 return json.dumps(point,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')

def read_source(client,name):
 offset=None; points=[]
 while True:
  request={'limit':100,'with_payload':True,'with_vector':True}
  if offset is not None:request['offset']=offset
  response=client.post(f'http://127.0.0.1:6333/collections/{name}/points/scroll',json=request)
  response.raise_for_status(); value=response.json()['result']; points.extend(value['points'])
  offset=value.get('next_page_offset')
  if offset is None:break
 return points

def digest(points):
 h=hashlib.sha256()
 for p in sorted(points,key=lambda x:str(x['id'])):h.update(canonical(p));h.update(b'\n')
 return h.hexdigest()

def design_versions(env_path, points):
 from dotenv import dotenv_values
 import psycopg
 from psycopg.conninfo import conninfo_to_dict

 dsn=dotenv_values(env_path)['POSTGRES_DSN'].replace('postgresql+psycopg://','postgresql://',1)
 config=conninfo_to_dict(dsn)
 if config.get('dbname')!='design_rag' or config.get('host') not in ('localhost','127.0.0.1','::1'):
  raise ValueError('Version backfill requires the local Design RAG authority database')
 with psycopg.connect(dsn, options='-c default_transaction_read_only=on',connect_timeout=10) as db:
  rows=db.execute('SELECT id,document_version_id FROM chunks WHERE id=ANY(%s)',
                  ([UUID(str(point['id'])) for point in points],)).fetchall()
 return {str(chunk):str(version) for chunk,version in rows}

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--design-env',type=Path,required=True,help='Private Design RAG environment file, read only')
 args=parser.parse_args()
 stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
 report={'created_at':stamp,'mode':'staging_snapshot','cutover':False,'collections':{}}
 target=MilvusClient(uri='http://127.0.0.1:19530',timeout=60)
 with httpx.Client(trust_env=False,timeout=60) as source:
  for src,prefix in [('manual_rag_chunks_v1','wk_manual'),('design_rag_chunks_v1','wk_design')]:
   name=prefix+'_snapshot_'+stamp
   if target.has_collection(name):raise RuntimeError('Destination already exists; refusing overwrite')
   source_points=read_source(source,src);before=digest(source_points)
   version_by_id=design_versions(args.design_env,source_points) if prefix=='wk_design' else None
   orphans=[]
   points=[]
   for point in source_points:
    payload=dict(point.get('payload') or {})
    if version_by_id is not None:
     version=version_by_id.get(str(point['id']))
     if version is None:
      orphans.append(str(point['id']))
      continue
     payload['document_version_id']=version
    points.append({**point,'payload':payload})
   schema=target.create_schema(auto_id=False,enable_dynamic_field=False)
   schema.add_field(field_name='id',datatype=DataType.VARCHAR,is_primary=True,max_length=128)
   schema.add_field(field_name='dense',datatype=DataType.FLOAT_VECTOR,dim=1024)
   schema.add_field(field_name='sparse',datatype=DataType.SPARSE_FLOAT_VECTOR,nullable=True)
   schema.add_field(field_name='payload',datatype=DataType.JSON)
   indices=target.prepare_index_params()
   indices.add_index(field_name='dense',index_type='AUTOINDEX',metric_type='COSINE')
   indices.add_index(field_name='sparse',index_type='SPARSE_INVERTED_INDEX',metric_type='IP')
   target.create_collection(collection_name=name,schema=schema,index_params=indices)
   report['collections'][src]={'destination':name,'source_count':len(source_points),'eligible_count':len(points),
                              'orphan_ids':orphans,'source_sha256':before,'state':'copying'}
   try:
    for start in range(0,len(points),100):
     rows=[]
     for p in points[start:start+100]:
      v=p['vector'];s=v['sparse'];rows.append({'id':str(p['id']),'dense':v['dense'],
       'sparse':dict(zip(s['indices'],s['values'],strict=True)) or None,'payload':p['payload']})
     target.upsert(collection_name=name,data=rows)
     print(json.dumps({'collection':src,'copied':min(start+100,len(points)),'total':len(points)}),flush=True)
    target.flush(collection_name=name)
    target.load_collection(collection_name=name)
    count=target.query(collection_name=name,filter='',output_fields=['count(*)'],consistency_level='Strong')[0]['count(*)']
    after_points=read_source(source,src);after=digest(after_points)
    sample=points[::max(1,len(points)//25)]
    received=target.get(collection_name=name,ids=[str(p['id']) for p in sample],output_fields=['id','payload','dense','sparse'],consistency_level='Strong')
    by_id={str(p['id']):p for p in received}; errors=[]
    for p in sample:
     q=by_id.get(str(p['id']))
     if not q or q['payload']!=(p.get('payload') or {}):errors.append('missing_id_or_payload');continue
     if len(q['dense'])!=len(p['vector']['dense']) or max(abs(a-b) for a,b in zip(q['dense'],p['vector']['dense']))>1e-5:errors.append('dense_mismatch')
     actual=q['sparse'] or {} if not hasattr(q['sparse'],'tocoo') else q['sparse']
     if hasattr(actual,'tocoo'):
      coo=actual.tocoo();actual=dict(zip(coo.col,coo.data))
     actual={int(k):float(v) for k,v in dict(actual).items()}
     expected=dict(zip(p['vector']['sparse']['indices'],p['vector']['sparse']['values']))
     if set(actual)!=set(expected) or any(abs(actual[k]-expected[k])>1e-5 for k in expected):errors.append('sparse_mismatch')
    info=report['collections'][src]
    ids={str(p['id']) for p in points}
    round_trip_ids=set()
    sorted_ids=sorted(ids)
    for start in range(0,len(sorted_ids),100):
     round_trip_ids.update(str(row['id']) for row in target.get(name,ids=sorted_ids[start:start+100],
                                                               output_fields=['id'],consistency_level='Strong'))
    if ids!=round_trip_ids:errors.append('full_id_set_mismatch')
    info.update(destination_count=count,source_count_after=len(after_points),source_sha256_after=after,
     source_unchanged_during_copy=before==after,sampled=len(sample),sample_errors=errors,
     state='snapshot_verified' if count==len(points) and before==after and not errors else 'needs_review')
   finally:
    out=ROOT/'data/manuals/runtime/milvus-migration';out.mkdir(parents=True,exist_ok=True)
    (out/('snapshot-'+stamp+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
   if report['collections'][src]['state']!='snapshot_verified':raise RuntimeError('Snapshot check failed or source changed')
 print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
