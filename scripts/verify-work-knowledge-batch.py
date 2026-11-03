"""Read-only batch acceptance through the existing LangBot knowledge connector."""
import importlib.util
import json
from pathlib import Path
import time

import httpx

ROOT=Path(__file__).resolve().parents[1]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def main():
    batch=module('batch',ROOT/'scripts/import-work-knowledge-batch.py')
    specs=list(batch.prepared());items=[]
    for spec,plan in specs:
        folder=ROOT/'data/manuals/runtime/mineru-imports'/plan['source_sha256']
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        items.append((spec,plan,manifest))
    with httpx.Client(base_url='http://127.0.0.1:8060',timeout=30) as client:
        limit=time.monotonic()+900;last=None
        while True:
            entries=[client.get('/api/v1/manuals/entries/'+m['entry_id']).json() for _,_,m in items]
            states=[(e['status'],e['index_status']) for e in entries]
            if states!=last:print(json.dumps({'states':states}),flush=True);last=states
            if all(s==('published','indexed') for s in states):break
            if any(s[1]=='failed' for s in states) or time.monotonic()>limit:raise RuntimeError('资料尚未全部索引，停止检索验收')
            time.sleep(10)
        category=next(c['id'] for c in client.get('/api/v1/manuals/categories').json() if c['name']=='人力行政中心')
        for (spec,plan,manifest),entry in zip(items,entries):
            assert entry['category_id']==category
            assert len(entry['assets'])==len(plan['images']) and len(entry['steps'])==len(plan['steps'])
            assert all(g['confirmed'] for g in entry['groups'])
            for asset in entry['assets']:
                response=client.get(asset['thumbnail_url']);response.raise_for_status()
                assert response.headers['content-type'].startswith('image/')
            if Path(spec['source']).suffix=='.txt':assert all(s['page'] is None for s in entry['steps'])
    conn=module('connection',ROOT/'scripts/connect-langbot-knowledge.py')
    report={'entries':[{'entry_id':e['id'],'title':e['title'],'version':e['version'],'status':e['status'],
                       'index_status':e['index_status'],'parents':len(e['groups']),'children':len(e['steps']),
                       'images':len(e['assets'])} for e in entries],'cases':[]}
    # No passwords, addresses or command strings are saved in the public report.
    cases=[
        (0,'设计师在A、B、C类城市的住宿限额分别是什么？',['设计师','500','450','400'],1),
        (1,'申请新增或更换设备需要怎样提交？',['邮件','IT'],None),
        (2,'这份教程中有哪些菜单和激活状态选项？',['Activation Methods','Check Activation Status'],None),
        (3,'1018打印机的地址记录是什么？',['1018'],None),
        (4,'如何使用Foxmail登录腾讯企业邮箱？',['Foxmail','腾讯企业邮'],3),
        (4,'1016打印机放在哪里？',['1016','一楼门口'],5),
    ]
    with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':conn.credential()},timeout=180) as client:
        for index,question,words,page in cases:
            started=time.monotonic();query=items[index][0]['title']+'\n'+question
            result=conn.data(client.post(f'/api/v1/knowledge/bases/{conn.KB}/retrieve',json={'query':query}))['results']
            selected=[r['metadata']['knowledge'] for r in result if
                r.get('metadata',{}).get('knowledge',{}).get('entry_id')==entries[index]['id'] and
                r['metadata']['knowledge'].get('result_type')=='source_evidence']
            steps=[s for packet in selected for s in packet.get('steps',[])]
            text='\n'.join(s.get('instruction','') for s in steps)
            exact=True
            if index==3:
                original_line=next(line.strip() for line in Path(items[index][0]['source']).read_text(encoding='utf-8-sig').splitlines() if '1018' in line)
                exact=original_line in text
            row={'title':items[index][0]['title'],'question':question,'entry_hit':bool(selected),
                 'keywords_present':all(w in text for w in words),'exact_record_preserved':exact,
                 'original_page_correct':any((s.get('source') or {}).get('page')==page for s in steps) if page else all((s.get('source') or {}).get('page') is None for s in steps),
                 'version_preserved':all(p.get('version')==entries[index]['version'] for p in selected),
                 'matched_children':sum(bool(s.get('is_match')) for s in steps),'seconds':round(time.monotonic()-started,2)}
            row['passed']=all(row[k] for k in ('entry_hit','keywords_present','exact_record_preserved','original_page_correct','version_preserved')) and row['matched_children']>0
            report['cases'].append(row);print(json.dumps(row,ensure_ascii=True),flush=True)
    report.update(passed=all(r['passed'] for r in report['cases']),
                  parents=sum(e['parents'] for e in report['entries']),children=sum(e['children'] for e in report['entries']),
                  images=sum(e['images'] for e in report['entries']),thumbnails_verified=True,
                  retrieval_mode='Default LangBot retrieval; title + question, no entry filter',platform_messages_sent=0)
    out=ROOT/'output/work-knowledge-batch-20261030';out.mkdir(parents=True,exist_ok=True)
    (out/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'entries':len(entries),'images':report['images'],'report':str(out/'verification.json')},ensure_ascii=True))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
