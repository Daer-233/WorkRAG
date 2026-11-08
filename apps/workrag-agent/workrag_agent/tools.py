import json
import threading
from uuid import UUID

import httpx


class Backend:
    def __init__(self,base_url='http://127.0.0.1:8060'):
        self.base_url=base_url
        self.client=httpx.Client(base_url=base_url,headers={'Host':'127.0.0.1:8060','X-Manual-Request':'1'},
                                 trust_env=False,timeout=150)
        self.heavy=threading.BoundedSemaphore(1)
        self.waiters=threading.BoundedSemaphore(32)

    def request(self,method,path,**kwargs):
        r=self.client.request(method,path,**kwargs)
        if r.status_code==404: raise ValueError('Document not found')
        r.raise_for_status()
        return r.json()

    def document(self,entry_id,version=None):
        UUID(str(entry_id))
        entry=self.request('GET',f'/api/v1/manuals/entries/{entry_id}')
        if entry['status']!='published' or entry['processing_status']!='ready':
            raise PermissionError('Document is not currently published')
        if version is not None and entry.get('version','')!=version: raise PermissionError('Document version changed')
        return entry

    def valid_refs(self,refs):
        try:
            for ref in refs: self.document(ref['entry_id'],ref['version'])
            return bool(refs)
        except (ValueError,KeyError,PermissionError,httpx.HTTPError): return False

    def search(self,query,allowed,top_k=5):
        if not self.waiters.acquire(blocking=False): return {'status':'busy','results':[]}
        try:
            with self.heavy:
                results=[]; limitations=[]
                for eid in allowed[:20]:
                    try: self.document(eid)
                    except (PermissionError,ValueError): continue
                    value=self.request('POST','/api/v1/manuals/retrieve',json={'query':query,'top_k':top_k,'filters':{'entry_id':eid}})
                    if value.get('status')=='busy': return value
                    results.extend(value.get('results',[])); limitations.extend(value.get('limitations',[]))
                results=[r for r in results if r.get('metadata',{}).get('result_type')=='source_evidence']
                return {'status':'ok' if results else 'insufficient_evidence','results':results[:top_k],'limitations':limitations}
        finally: self.waiters.release()

    def followup(self,kind,entry_id,version,query,cursor=None):
        self.document(entry_id,version)
        envelope={'entry_id':entry_id,'version':version,'followup':kind}
        if cursor: envelope['cursor']=cursor
        return self.request('POST','/api/v1/manuals/retrieve',json={'query':'@knowledge '+json.dumps(envelope)+'\n'+query,'top_k':5})


def extract_refs(value):
    refs=[]
    for result in value.get('results',[]):
        meta=result.get('metadata',{})
        if meta.get('result_type')!='source_evidence': continue
        if not meta.get('entry_id'): continue
        ref={k:meta.get(k,'') for k in ('entry_id','title','version')}
        ref['evidence_ids']=[eid for step in meta.get('steps',[]) for eid in step.get('evidence_ids',[])]
        matched=[s for s in meta.get('steps',[]) if s.get('is_match') and len(s.get('evidence_ids',[]))==1]
        if len(matched)==1: ref['cursor']=matched[0]['evidence_ids'][0]
        refs.append(ref)
    return refs


class ToolService:
    def __init__(self,store,backend,secret):
        self.store,self.backend,self.secret=store,backend,secret

    def call(self,name,args,scope_token):
        from .security import verify_scope
        scope=verify_scope(self.secret,scope_token)
        allowed=scope['entries']; identity=scope['identity']
        if name=='search_my_history':
            return {'status':'ok','history':self.store.search_history(identity,str(args.get('query','')),int(args.get('limit',10)))}
        if name=='search_knowledge':
            value=self.backend.search(str(args['query'])[:4000],allowed,min(max(int(args.get('top_k',5)),1),10))
            return self.restrict(value,allowed)
        eid=str(args.get('entry_id',''))
        if eid not in allowed: raise PermissionError('Document is outside this run scope')
        kind={'get_document_images':'images','get_source_file':'source_file'}.get(name)
        if not kind: raise ValueError('Unknown read-only tool')
        if args.get('mode')=='next_step' and name=='get_document_images': kind='next_step'
        value=self.backend.followup(kind,eid,str(args.get('version','')),str(args.get('query','请展示对应资料')),
                                    args.get('cursor'))
        return self.restrict(value,[eid])

    def restrict(self,value,allowed):
        # Recheck the returned identity, even if a structured query is parsed by
        # the existing backend or its filter implementation changes later.
        retained=[]
        for result in value.get('results',[]):
            refs=extract_refs({'results':[result]})
            if refs and all(r['entry_id'] in allowed for r in refs) and self.backend.valid_refs(refs):
                retained.append(result)
        return {**value,'results':retained,'status':value.get('status','ok') if retained or value.get('status')!='ok' else 'insufficient_evidence'}
