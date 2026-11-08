"""Check isolated Milvus with a uniquely named temporary collection."""
import json
import time
import uuid
import httpx

name='workknowledge_smoke_'+uuid.uuid4().hex[:12]
created=False
with httpx.Client(base_url='http://127.0.0.1:19530',timeout=30,trust_env=False) as client:
    def call(path,body):
        response=client.post('/v2/vectordb/'+path,json=body)
        response.raise_for_status()
        result=response.json()
        if result.get('code')!=0:raise RuntimeError(str(result))
        return result
    try:
        call('collections/create',{'collectionName':name,'dimension':4,'metricType':'COSINE'})
        created=True
        call('entities/insert',{'collectionName':name,'data':[{'id':1,'vector':[1.0,0.0,0.0,0.0]}]})
        found=False
        for attempt in range(15):
            result=call('entities/search',{'collectionName':name,'data':[[1.0,0.0,0.0,0.0]],'limit':1,'consistencyLevel':'Strong'})
            if result.get('data'):
                found=True;break
            time.sleep(2)
        if not found:raise RuntimeError('Inserted vector was not returned by search')
        print(json.dumps({'create':True,'insert':True,'search':True,'temporary_collection':name}))
    finally:
        if created:call('collections/drop',{'collectionName':name})
