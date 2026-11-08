"""Real DeepSeek and MCP acceptance for the isolated Pi debug processor."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import json
import sys
import time
from uuid import uuid4
from dotenv import dotenv_values
from langgraph.checkpoint.postgres import PostgresSaver
from install_agent import ROOT,RUNTIME,client,data

def verify():
    sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
    from workrag_agent.store import Store
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'));c=client()
    agent=data(c.get('/api/v1/agents/'+binding['agent_id']))['agent'];config=agent['config'];settings=config['runner_config'][config['runner']['id']]
    assert settings['engine']=='pi' and not settings.get('simulation')
    prefix='pi-acceptance-'+uuid4().hex[:10];records=[]
    path=RUNTIME/'pi-real-acceptance.json'
    def save():path.write_text(json.dumps({'engine':'pi-agent-core@1.5.0','real_model':True,'checks':records},ensure_ascii=False,indent=2),encoding='utf-8')
    def debug(label,text,conversation=None,user='pi-acceptance-alice'):
        start=time.monotonic();response=data(c.post('/api/v1/agents/'+binding['agent_id']+'/debug',json={'text':text,
            'conversation_id':conversation or prefix,'actor':{'actor_type':'user','actor_id':user}}))
        with store.connection() as conn:row=conn.execute('SELECT * FROM wa_answers WHERE event_id=%s',(response['event_id'],)).fetchone()
        assert row is not None
        with PostgresSaver.from_conn_string(store.dsn) as saver:state=saver.get_tuple({'configurable':{'thread_id':row['session_key']}}).checkpoint['channel_values']
        calls=[call['function']['name'] for m in state.get('messages',[]) for call in m.get('tool_calls',[])]
        record={'label':label,'event_id':response['event_id'],'seconds':round(time.monotonic()-start,2),
                'answer':response.get('final_text'),'refs':row['refs'],'calls':calls,'call_count':state.get('call_count'),
                'intent':state.get('intent'),'route':state.get('route'),'simulation':row['simulation']}
        records.append(record);save()
        assert not row['simulation'] and '模型暂时不可用' not in record['answer'],label
        print(label,'seconds',record['seconds'],'calls',calls,'refs',len(row['refs']),flush=True)
        return record,response
    greeting,_=debug('daily','日常问题：1+1等于几？只回复数字。',prefix+'-daily');assert '2' in greeting['answer'];greeting['passed']=True;save()
    knowledge,knowledge_response=debug('knowledge','请仅查询《演示企业｜设备借用演练（虚构测试资料）》，确认借用时核对的设备编号是什么？引用资料标题、版本和证据 ID。')
    assert 'DEMO-LAPTOP-008' in knowledge['answer'] and knowledge['refs'] and 'search_knowledge' in knowledge['calls'];knowledge['passed']=True;save()
    assert 'demo-v1' not in knowledge['answer']
    assert all(e not in knowledge['answer'] for r in knowledge['refs'] for e in r.get('evidence_ids',[]))
    snapshots=[e['data']['chunk'].get('all_content','') for e in knowledge_response.get('execution_events',[]) if e.get('type')=='message.delta']
    assert snapshots and all('demo-v1' not in text for text in snapshots)
    assert all(e not in text for text in snapshots for r in knowledge['refs'] for e in r.get('evidence_ids',[]))
    for label,question,kind in [('images','图片','image_base64'),('file','文件','file_base64')]:
        record,response=debug(label,question)
        content=next((e.get('data',{}).get('message',{}).get('content') for e in response.get('execution_events',[]) if e.get('type')=='run.completed'),[])
        assert isinstance(content,list) and any(p.get('type')==kind for p in content),label
        record['passed']=True;save()
    other,_=debug('other_user_followup','图片',user='pi-acceptance-bob');assert '请说明' in other['answer'] and not other['refs'];other['passed']=True;save()
    history,_=debug('personal_history','仅查询我自己的历史，找出我问过的设备借用问题。不要检索知识库。',prefix+'-history')
    assert 'search_my_history' in history['calls'];history['passed']=True;save()
    missing,_=debug('no_evidence','请检索公司已发布资料：火星出差住宿补贴金额是多少？没有依据就明确说明。',prefix+'-missing')
    assert '没有足够证据' in missing['answer'] or any(w in missing['answer'] for w in ['没有','未找到','未提供','无法','不足']);missing['passed']=True;save()
    save();print('PASS',len(records),'real Pi model/MCP checks',flush=True)

if __name__=='__main__':verify()
