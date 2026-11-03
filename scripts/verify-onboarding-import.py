"""Read-only stored-draft/index/LangBot acceptance. No model or message delivery."""
import argparse
import importlib.util
import json
from pathlib import Path
import time

import httpx

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--entry-id',required=True)
    parser.add_argument('--wait-index',action='store_true')
    args=parser.parse_args()
    with httpx.Client(base_url='http://127.0.0.1:8060',timeout=30) as local:
        deadline=time.monotonic()+900
        last=None
        while True:
            response=local.get('/api/v1/manuals/entries/'+args.entry_id);response.raise_for_status()
            entry=response.json()
            state=(entry['status'],entry['index_status'])
            if state!=last: print(json.dumps({'status':state[0],'index':state[1]}),flush=True);last=state
            if not args.wait_index or entry['index_status']=='indexed':break
            if entry['index_status']=='failed' or time.monotonic()>deadline:raise RuntimeError('索引未完成，停止检索验收')
            time.sleep(10)
        assert len(entry['assets'])==28 and len(entry['groups'])==8
        assert all(g['confirmed'] for g in entry['groups'])
        for image in entry['assets']:
            response=local.get(image['thumbnail_url']);response.raise_for_status()
            assert response.headers.get('content-type','').startswith('image/')
    spec=importlib.util.spec_from_file_location('connection',ROOT/'scripts/connect-langbot-knowledge.py')
    conn=importlib.util.module_from_spec(spec);spec.loader.exec_module(conn)
    cases=[
        ('补卡次数','每月补卡有几次机会？',['补卡','3次'],6),
        ('流程时效','加班、补卡、调休、出差流程多久有效？',['30天'],6),
        ('差旅预订','如何预订出差机票和酒店？',['滴滴商旅','机票'],11),
        ('IT故障','IT设备故障应该如何处理？',['故障','IT'],17),
        ('报销流程','费用报销需要经过哪些流程？',['发票'],20),
        ('付款申请','付款申请线上如何操作？',['钉钉'],23),
    ]
    report={'entry_id':args.entry_id,'title':entry['title'],'status':entry['status'],
        'index_status':entry['index_status'],'assets':len(entry['assets']),'parents':len(entry['groups']),
        'children':len(entry['steps']),'unknown_text_pages':sum(s['page'] is None for s in entry['steps']),
        'thumbnails_accessible':28,'cases':[]}
    with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':conn.credential()},timeout=180) as client:
        for name,question,words,page in cases:
            query='@knowledge '+json.dumps({'entry_id':args.entry_id})+'\n'+question
            started=time.monotonic()
            result=conn.data(client.post(f'/api/v1/knowledge/bases/{conn.KB}/retrieve',json={'query':query}))['results']
            metas=[i.get('metadata',{}).get('knowledge',{}) for i in result]
            selected=[m for m in metas if m.get('entry_id')==args.entry_id and m.get('result_type')=='source_evidence']
            steps=[s for m in selected for s in m.get('steps',[])]
            matched=[s for s in steps if s.get('is_match')]
            text='\n'.join(s.get('instruction','') for s in steps)
            row={'name':name,'question':question,'entry_hit':bool(selected),'keywords_present':all(w in text for w in words),
                'expected_page':page,'page_present':any((s.get('source') or {}).get('page')==page for s in steps),
                'matched_children':len(matched),'seconds':round(time.monotonic()-started,2)}
            row['passed']=row['entry_hit'] and row['keywords_present'] and row['page_present'] and bool(matched)
            report['cases'].append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
        started=time.monotonic()
        results=conn.data(client.post(f'/api/v1/knowledge/bases/{conn.KB}/retrieve',json={
            'query':'LSD新员工入职培训中，每月补卡次数有多少？'}))['results']
        report['default_query_visible']=any(i.get('metadata',{}).get('knowledge',{}).get('entry_id')==args.entry_id for i in results)
        report['default_query_seconds']=round(time.monotonic()-started,2)
    report['passed']=all(c['passed'] for c in report['cases']) and report['default_query_visible']
    folder=ROOT/'output/onboarding-import-20261030';folder.mkdir(parents=True,exist_ok=True)
    (folder/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'default_query_visible':report['default_query_visible'],
        'report':str(folder/'verification.json')},ensure_ascii=True))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__': main()
