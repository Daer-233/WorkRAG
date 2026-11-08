"""Synthetic local acceptance through actual LangBot debug and Page APIs; no bot sends."""

# Direct invocation resolves the shared deployment helpers.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
import asyncio
import json
import sys
import time
from uuid import uuid4
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,client,data

sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
from workrag_agent.store import Store
from workrag_agent.tools import Backend
from workrag_agent.security import identity_key

def verify():
    c=client(); binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'))
    aid=binding['agent_id']; workspace=binding['workspace']
    installed=data(c.get('/api/v1/agents/'+aid))['agent']['config']
    if not installed['runner_config'][installed['runner']['id']].get('simulation'):
        raise ValueError('This script requires the simulation processor; use verify_real_model.py for the enabled real model')
    private=dotenv_values(ROOT/'data/manuals/runtime/agent.env'); store=Store(private['WORKRAG_AGENT_DSN'])
    prefix='acceptance-'+uuid4().hex[:8]; passed=[]
    def check(name,ok):
        if not ok: raise AssertionError(name)
        passed.append(name); print('PASS',name,flush=True)
    def debug(text='',user='acceptance-alice',conversation=None,**kwargs):
        return data(c.post('/api/v1/agents/'+aid+'/debug',json={'text':text,
            'actor':{'actor_type':'user','actor_id':user},'conversation_id':conversation or prefix,**kwargs}))
    def page(endpoint,method='GET',body=None):
        return data(c.post('/api/v1/plugins/workrag/WorkRAGGraph/page-api',json={
            'page_id':'review','endpoint':endpoint,'method':method,'body':body}))
    check('greeting_stream_events',any(e['type']=='message.delta' for e in debug('你好')['execution_events']))
    answer=debug('部署验收测试编号是什么（本次验收 '+prefix+'）')
    check('real_mcp_knowledge_evidence','WRAG-LOCAL-20261107' in answer['final_text'])
    with store.connection() as con:
        row=con.execute('SELECT * FROM wa_answers WHERE event_id=%s',(answer['event_id'],)).fetchone()
    check('persisted_answer_with_sources',bool(row and row['refs']))
    check('other_user_cannot_followup','请说明' in debug('需要截图',user='acceptance-bob')['final_text'])
    check('source_file_followup','deployment-smoke.docx' in debug('需要原文件')['final_text'])
    # A subsequent topic has no pending attachment, and expired/ambiguous actions are covered in pytest.
    check('personal_history_tool','以下是你自己的历史记录' in debug('我上次问过什么')['final_text'])
    fid='feedback-'+uuid4().hex
    feedback={'feedback_id':fid,'feedback_type':1,'message_id':str(row['id']),'user_id':'acceptance-alice'}
    debug(event_type='feedback.received',data=feedback)
    debug(event_type='feedback.received',data=feedback)
    candidates=page('/candidates')['candidates']; candidate=next(x for x in candidates if x['answer_id']==str(row['id']))
    check('positive_feedback_candidate_and_callback_dedup',candidate['state']=='pending')
    # Use the identity actually recorded by the Host, rather than assuming its bot/session defaults.
    with store.connection() as con: ident=con.execute('SELECT identity FROM wa_sessions WHERE session_key=%s',(row['session_key'],)).fetchone()['identity']
    check('not_reusable_before_review',store.reuse(ident,row['question'],[binding['sample_entry_id']],Backend().valid_refs,True) is None)
    negative={**feedback,'feedback_id':fid+'-changed','feedback_type':2,'feedback_content':'模拟改评：请检查表述'}
    debug(event_type='feedback.received',data=negative)
    check('changed_feedback_retained',next(x for x in page('/candidates')['candidates'] if x['id']==candidate['id'])['feedback'][0]['vote']=='negative')
    edited=page('/review','POST',{'id':candidate['id'],'action':'edit','revision':candidate['revision'],
        'question':row['question'],'answer':'【模拟模型验收】验收编号为 WRAG-LOCAL-20261107。来源：部署验收示例（非真实业务制度）。',
        'conditions':'','privacy_checked':True})
    published=page('/review','POST',{'id':candidate['id'],'action':'publish','revision':edited['revision']})
    check('admin_page_publish',published['state']=='published')
    reused=debug(row['question'],conversation=prefix+'-reuse')
    check('published_qa_reuse',len(reused['final_text'])<200 and 'WRAG-LOCAL-20261107' in reused['final_text'])
    unpublished=page('/review','POST',{'id':candidate['id'],'action':'unpublish','revision':published['revision']})
    check('unpublished_qa_stops_reuse',store.reuse(ident,row['question'],[binding['sample_entry_id']],Backend().valid_refs,True) is None)
    # Leave an explicitly synthetic approved answer visible for the reviewer, isolated from real mode.
    page('/review','POST',{'id':candidate['id'],'action':'publish','revision':unpublished['revision']})
    import httpx
    r=httpx.post('http://127.0.0.1:5300/api/v1/plugins/workrag/WorkRAGGraph/page-api',json={
        'page_id':'review','endpoint':'/review','method':'POST','body':{}},trust_env=False)
    check('anonymous_review_rejected',r.status_code==401)
    check('mcp_requires_auth',httpx.post('http://127.0.0.1:8061/mcp',json={},trust_env=False).status_code==401)
    original_response=c.get('/api/v1/pipelines/9140e5df-003f-40eb-846b-c08538b28891')
    change_file=RUNTIME/'post-acceptance-changes.json'
    removed_by_user=change_file.exists() and json.loads(change_file.read_text(encoding='utf-8')).get('user_confirmed_removal') is True
    if removed_by_user:
        check('user_requested_original_removal_preserved',original_response.status_code==404)
    else:
        original=data(original_response)['pipeline']
        check('original_local_agent_preserved','LocalAgent' in json.dumps(original['config']))
    pipeline=data(c.post('/api/v1/pipelines/'+binding['pipeline_id']+'/run',json={'message':row['question']}))
    check('pipeline_scheduler_and_output',pipeline['status']=='completed' and 'WRAG-LOCAL-20261107' in pipeline['reply'])
    pipeline_config=data(c.get('/api/v1/pipelines/'+binding['pipeline_id']))['pipeline']['config']
    import copy
    changed=copy.deepcopy(pipeline_config)
    changed['trigger']['ignore-rules']['regexp']=['^WRAG-IGNORE$']
    try:
        data(c.put('/api/v1/pipelines/'+binding['pipeline_id'],json={'config':changed}))
        ignored=data(c.post('/api/v1/pipelines/'+binding['pipeline_id']+'/run',json={'message':'WRAG-IGNORE'}))
        check('pipeline_trigger_rule_effective',not ignored.get('reply') and ignored.get('replies')==[])
    finally: data(c.put('/api/v1/pipelines/'+binding['pipeline_id'],json={'config':pipeline_config}))
    # Host-owned RPC must honor the workflow deadline too, not just direct graph tests.
    original_config=data(c.get('/api/v1/agents/'+aid))['agent']['config']
    changed=copy.deepcopy(original_config)
    runner_id=changed['runner']['id']; settings=changed['runner_config'][runner_id]
    settings.update(timeout=1,max_calls=1,reuse=False)
    try:
        data(c.put('/api/v1/agents/'+aid,json={'config':changed}))
        started=time.monotonic()
        timed=c.post('/api/v1/agents/'+aid+'/debug',json={'text':'__test_timeout__','conversation_id':prefix+'-timeout',
            'actor':{'actor_type':'user','actor_id':'acceptance-alice'}})
        # Host may reach its invocation deadline before the graph's inner timer.
        timeout_ok=(timed.status_code==422 and timed.json().get('code')=='runner.timeout') or (
            timed.status_code==200 and '超时' in data(timed).get('final_text',''))
        check('actual_runner_timeout_cancels_model',time.monotonic()-started<10 and timeout_ok)
        settings['timeout']=30
        data(c.put('/api/v1/agents/'+aid,json={'config':changed}))
        check('actual_runner_model_error','模型暂时不可用' in debug('__test_model_error__',conversation=prefix+'-model-error')['final_text'])
        check('actual_runner_tool_limit','上限' in debug('__test_loop__',conversation=prefix+'-tool-limit')['final_text'])
        settings['tools']=[]
        data(c.put('/api/v1/agents/'+aid,json={'config':changed}))
        check('actual_host_tool_grants_enforced','没有访问' in debug('部署验收',conversation=prefix+'-no-grant')['final_text'])
    finally:data(c.put('/api/v1/agents/'+aid,json={'config':original_config}))
    report={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'checks':passed,'sample_candidate_id':candidate['id'],
        'answer_id':str(row['id']),'session_key':row['session_key'],'binding':binding,
        'simulation':True,'real_llm_verified':False,'real_dingtalk_verified':False}
    (RUNTIME/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved local agent acceptance record')

if __name__=='__main__': verify()
