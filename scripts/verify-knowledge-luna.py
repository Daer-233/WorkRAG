"""Small real Pipeline acceptance set; never re-submit unknown executions."""
from __future__ import annotations
import json
from pathlib import Path
import re
import shutil
import time

import httpx
from knowledge_connection_watchdog import connection

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'data/manuals/runtime/luna-verification'
PUBLIC=ROOT/'output/model-migration-luna-20261103'
CASES=[('attendance','《LSD新员工入职培训》中，每月补卡机会几次，流程时效多久？请引用来源页码。'),
       ('no_evidence','公司是否明文规定给每位新员工发放一台私人游戏机？仅按现有资料回答，没有依据就明确说明。'),
       ('photos','请展示AI赋能设计培训现场照片，优先老师画面，其次实训和全景。不要推断照片中的课程步骤。')]


def plain(value):
    if isinstance(value,str):
        try: return plain(json.loads(value))
        except ValueError: return value
    if isinstance(value,list): return '\n'.join(plain(x) for x in value)
    if isinstance(value,dict): return str(value.get('text',''))
    return ''


def follow(client,conn,result,path):
    until=time.monotonic()+150
    while time.monotonic()<until:
        try:
            data=conn.data(client.get('/api/v1/monitoring/messages',params={'sessionId':result['session_id'],'limit':8}))
        except httpx.TransportError:
            # Retrying an observation is safe; never repeat the model POST.
            time.sleep(2)
            continue
        completed=[m for m in data.get('messages',[]) if m.get('role')=='assistant' and m.get('status')=='success']
        if completed:
            result.update(status='completed',reply=plain(completed[0].get('message_content','')),followed_original_session=True)
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
        if any(m.get('status') in ('error','failed','cancelled') for m in data.get('messages',[])):
            result['status']='failed'
            return result
        time.sleep(5)
    return result


def main():
    PRIVATE.mkdir(parents=True,exist_ok=True);PUBLIC.mkdir(parents=True,exist_ok=True)
    if (PUBLIC/'acceptance.json').exists() and not (PUBLIC/'acceptance-initial.json').exists():
        shutil.copy2(PUBLIC/'acceptance.json',PUBLIC/'acceptance-initial.json')
    conn=connection();report=[]
    with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':conn.credential()},
            timeout=75,trust_env=False,limits=httpx.Limits(max_keepalive_connections=0)) as client:
        conn.data(client.get(f'/api/v1/pipelines/{conn.PIPELINE}'))
        with httpx.Client(timeout=20,headers={'X-Manual-Request':'1'}) as library:
            response=library.get('http://127.0.0.1:8060/api/v1/manuals/entries/1fd0f00d-962d-46a4-b8ff-75701e1db875')
            response.raise_for_status();entry=response.json();entry=entry.get('entry',entry)
            allowed={str(a['id'] if 'id' in a else a['asset_id']) for a in entry.get('assets',[])}
            response=library.get('http://127.0.0.1:8060/api/v1/manuals/entries/f6f90cba-2f07-4df2-874b-03b7f0c64232')
            response.raise_for_status();policy=response.json();policy=policy.get('entry',policy)
            policy_ids={str(step.get('evidence_id')) for step in policy.get('steps',[])}
        for name,question in CASES:
            path=PRIVATE/(name+'.private.json')
            if path.exists():
                result=json.loads(path.read_text(encoding='utf-8'))
                if result.get('status')=='submitted': raise RuntimeError('Unknown submission; inspect existing execution instead of retrying')
            else:
                started=time.time()
                path.write_text(json.dumps({'status':'submitted','started_at':started}),encoding='utf-8')
                result=conn.data(client.post(f'/api/v1/pipelines/{conn.PIPELINE}/run',json={'message':question}))
                result['started_at']=started
                path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            if result.get('status')=='unknown' and result.get('session_id'):
                result=follow(client,conn,result,path)
            answer=plain(result.get('reply',''))
            checks={'completed':result.get('status')=='completed'}
            if name=='attendance':
                checks.update(correct_count=bool(re.search(r'(?:3|三)\s*次',answer)),
                    correct_time_limit=bool(re.search(r'(?:30|三十)\s*天',answer)),
                    has_source='LSD新员工入职培训' in answer,
                    has_page=bool(re.search(r'第\s*(?:6|六)\s*页|页码[：:\s]*6|[｜|·]\s*(?:P|p)\.?\s*6',answer)),
                    has_source_file_offer=bool(re.search(r'需要.{0,30}(?:源文件|整理稿|原文件)',answer)))
            elif name=='no_evidence':
                checks['explicitly_unsupported']=bool(re.search(r'未.{0,18}(?:找到|检索|见|规定|依据|说明)|没有.{0,12}(?:依据|规定)|无法确认|证据不足',answer))
                offer=bool(re.search(r'需要.{0,30}(?:源文件|整理稿|原文件)',answer))
                references=set(re.findall(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',answer))
                # This query may retrieve real welfare evidence without the
                # requested rule. Offering that cited file is grounded, unlike
                # offering a file after an empty/failed retrieval.
                grounded=bool(references) and references<=policy_ids and bool(policy.get('source_url'))
                checks['no_unavailable_file_offer']=not offer or grounded
            else:
                ids=re.findall(r'/api/v1/manuals/assets/([0-9a-f-]{36})',answer)
                checks['has_photo_references']=bool(ids)
                checks['only_real_photo_assets']=bool(ids) and set(ids)<=allowed
            item={'case':name,'checks':checks,'passed':all(checks.values()),
                'elapsed_until_observation_seconds':round(time.time()-result.get('started_at',time.time()),2)}
            if name=='no_evidence' and grounded:
                item['review_note']='检索到真实福利资料但无游戏机发放规定；已核验引用，相关来源文件提醒有依据。'
            report.append(item)
            (PUBLIC/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(item),flush=True)
            if result.get('status') not in ('completed','failed'):
                break
    if len(report)!=len(CASES) or not all(r['passed'] for r in report):
        raise SystemExit('Acceptance has unresolved checks; see private original-session records.')


if __name__=='__main__':main()
