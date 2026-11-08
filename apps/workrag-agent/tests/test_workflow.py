import asyncio
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
if sys.platform=='win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from dotenv import dotenv_values
from langgraph.checkpoint.postgres import PostgresSaver

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
from workrag_agent.graph import Workflow,route_followup
from workrag_agent.model import SimulationModel
from workrag_agent.security import issue_scope,verify_scope,identity_key
from workrag_agent.store import Store
from workrag_agent.tools import ToolService
from workrag_agent.bridge import InvocationBridge

EID='00000000-0000-0000-0000-000000000001'
REF={'entry_id':EID,'title':'测试流程','version':'v1','evidence_ids':['e1']}
SECRET='test-secret-'+('a'*48)

class Backend:
    valid=True
    def valid_refs(self,refs): return self.valid and bool(refs)
    def search(self,query,allowed,top_k):
        if EID not in allowed: return {'status':'insufficient_evidence','results':[]}
        return {'status':'ok','results':[{'content':'测试流程 [e1] 测试编号 WRAG-TEST', 'metadata':{'result_type':'source_evidence',**REF,'steps':[{'evidence_ids':['e1']}]}}]}
    def followup(self,kind,entry_id,version,query,cursor=None):
        if version!='v1' or not self.valid: raise PermissionError()
        return {'status':'ok','results':[{'content':'测试流程 [e1] '+kind,'metadata':{'result_type':'source_evidence',**REF,
            'source_file':{'available':True,'name':'test-source_file.docx','kind':'archived_file'},
            'images':[{'name':'images.png','preview_url':'/api/v1/manuals/assets/test'}] if kind=='images' else [],
            'steps':[{'evidence_ids':['e1'],'order':2,'instruction':kind}]}}]}

@pytest.fixture(scope='session')
def dsn():
    config=dotenv_values(ROOT/'data/manuals/runtime/agent.env')
    dsn=config['WORKRAG_AGENT_DSN'].rsplit('/',1)[0]+'/workrag_agent_test'
    admin=dotenv_values(ROOT/'instances/manuals/.env')['POSTGRES_DSN']
    with psycopg.connect(admin,autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname='workrag_agent_test'").fetchone():
            c.execute('CREATE DATABASE workrag_agent_test OWNER workrag_agent')
    Store(dsn).setup()
    with PostgresSaver.from_conn_string(dsn) as saver: saver.setup()
    Store(dsn).setup()
    return dsn

@pytest.fixture
def env(dsn):
    ident={'workspace':'test-'+str(uuid4()),'bot':'test','processor':'test','conversation':'one','sender':'alice'}
    store=Store(dsn); backend=Backend(); tools=ToolService(store,backend,SECRET)
    return ident,store,backend,tools

def run(env,text,*,identity=None,event=None,model=None,options=None,allowed=None):
    ident,store,backend,tools=env
    async def tool(name,args): return tools.call(name,args,args['run_scope'])
    return asyncio.run(Workflow(store,backend,model or SimulationModel(),tool,SECRET,identity or ident,event or str(uuid4()),
                         [EID] if allowed is None else allowed,options).run(text))

def test_signed_scope_expiry_and_forgery(env):
    ident,*_=env
    token=issue_scope(SECRET,ident,[EID],'run')
    assert verify_scope(SECRET,token)['entries']==[EID]
    with pytest.raises(PermissionError): verify_scope(SECRET,token+'x')
    with pytest.raises(PermissionError): verify_scope(SECRET,issue_scope(SECRET,ident,[EID],'run',ttl=-1))

def test_host_calls_stay_on_owning_runner_task():
    async def scenario():
        owner=asyncio.current_task(); bridge=InvocationBridge()
        async def host_call(value):
            assert asyncio.current_task() is owner
            return value+1
        async def graph(): return await bridge.call(host_call,4)
        assert await bridge.run(graph())==5
        with pytest.raises(RuntimeError): await bridge.call(host_call,1)
    asyncio.run(scenario())


def test_graph_timeout_cancels_slow_rpc_on_owning_task():
    async def scenario():
        owner=asyncio.current_task(); bridge=InvocationBridge();closed=[]
        async def slow_host():
            assert asyncio.current_task() is owner
            try:await asyncio.sleep(300)
            finally:closed.append(True)
        async def graph():
            try:await asyncio.wait_for(bridge.call(slow_host),timeout=.05)
            except TimeoutError:return 'timed out'
        start=time.monotonic()
        assert await bridge.run(graph())=='timed out'
        assert time.monotonic()-start<1 and closed and not owner.cancelling()
    asyncio.run(scenario())


def test_streaming_rpc_yields_before_model_finishes_on_owner_task():
    async def scenario():
        owner=asyncio.current_task();bridge=InvocationBridge();completed=[];received=[]
        async def stream():
            assert asyncio.current_task() is owner
            yield {'type':'answer_delta','content':'第一段'}
            assert not completed
            await asyncio.sleep(.02)
            yield {'type':'answer_delta','content':'第一段第二段'}
            completed.append(True)
            yield {'type':'model_result','value':'final'}
        async def graph():return await bridge.call(stream)
        async for event in bridge.iterate(graph()):
            if event['type']=='answer_delta':
                assert not completed
                received.append(event['content'])
            else:assert event['value']=='final'
        assert received==['第一段','第一段第二段'] and not bridge.active
    asyncio.run(scenario())

def test_workflow_real_postgres_checkpoint_and_duplicate(env):
    r=run(env,'测试编号是什么',event='one')
    assert 'WRAG-TEST' in r['answer'] and r['refs'][0]['entry_id']==EID and r['answer_id']
    again=run(env,'测试编号是什么',event='one')
    assert again['answer_id']==r['answer_id']
    assert env[1].recent(identity_key(env[0]))[-1]['question']=='测试编号是什么'

def test_two_users_do_not_share_state_or_history(env):
    a=run(env,'测试编号是什么')
    bob={**env[0],'sender':'bob'}
    b=run(env,'需要截图',identity=bob)
    assert '请说明' in b['answer'] and b['refs']==[]
    assert env[1].search_history(bob,'测试编号')==[]
    with pytest.raises(PermissionError): env[1].feedback(bob,'bad',a['answer_id'],'positive')


def test_matching_sender_ids_on_different_bots_are_isolated(env):
    result=run(env,'测试编号')
    other_bot={**env[0],'bot':'different-platform-bot'}
    assert not env[1].search_history(other_bot,'测试编号')
    with pytest.raises(PermissionError): env[1].feedback(other_bot,'other-bot',result['answer_id'],'positive')

@pytest.mark.parametrize('text,kind',[('需要截图','images'),('需要原文件','source_file')])
def test_readonly_followups(env,text,kind):
    run(env,'测试编号是什么')
    r=run(env,text)
    assert kind in r['answer']
    assert '源文件提醒规则' not in r['answer'] and 'result_type' not in r['answer']


def test_next_step_followup_preserves_action_kind(env):
    ident,store,*_=env;store.session(ident)
    store.finish(ident,'step-seed','测试步骤','测试流程 [e1]',[{**REF,'cursor':'e1'}])
    result=run(env,'下一步')
    assert '步骤 2' in result['answer'] and 'next_step' in result['answer'] and result['call_count']==1


def test_followup_does_not_rename_next_independent_question(env):
    run(env,'测试编号')
    run(env,'需要原文件')
    run(env,'你好')
    assert env[1].recent(identity_key(env[0]))[-1]['question']=='你好'


def test_large_personal_history_keeps_valid_json(env):
    ident,store,*_=env
    store.session(ident)
    for _ in range(8):store.finish(ident,str(uuid4()),'部署历史','历史片段'*5000,[])
    result=run(env,'我上次问过什么')
    assert '以下是你自己的历史记录' in result['answer']
    assert store.recent(identity_key(ident))[-1]['question']=='我上次问过什么'

def test_pending_confirmation_cancel_expiry_and_multiple_sources():
    pending={'kind':'images','source':REF,'expires_at':time.time()+600}
    assert route_followup('需要',pending,[REF])[0]=='followup'
    assert route_followup('不用了',pending,[REF])[0]=='cancel'
    assert route_followup('需要',{**pending,'expires_at':0},[REF])[0]=='clarify'
    assert route_followup('需要截图',None,[REF,REF])[0]=='clarify'
    assert route_followup('换个问题',pending,[REF])==('new',None)
    assert route_followup('下一步',None,[REF])[0]=='clarify'
    assert route_followup('下一步',None,[{**REF,'cursor':'e1'}])[0]=='followup'


def test_resource_choice_is_explicit_and_does_not_default_to_image():
    pending={'kind':'choose_resource','source':REF,'expires_at':time.time()+600}
    assert route_followup('需要',pending,[REF])[0]=='clarify'
    assert route_followup('图片',pending,[REF])[1]['kind']=='images'
    assert route_followup('文件',pending,[REF])[1]['kind']=='source_file'
    assert route_followup('图片',pending,[REF,REF])[0]=='clarify'

def test_permissions_and_source_invalidation(env):
    r=run(env,'测试编号',allowed=[])
    assert not r['refs'] and '没有足够证据' in r['answer']
    run(env,'测试编号')
    env[2].valid=False
    r=run(env,'需要截图')
    assert '请说明' in r['answer']

def test_feedback_review_publish_reuse_and_unpublish(env):
    ident,store,backend,_=env
    r=run(env,'测试编号')
    assert store.reuse(ident,'测试编号',[EID],backend.valid_refs) is None
    store.feedback(ident,'positive',r['answer_id'],'positive')
    assert store.feedback(ident,'positive',r['answer_id'],'negative')['duplicate']
    candidate=store.candidates(ident['workspace'])[0]
    assert candidate['state']=='pending'
    with pytest.raises(ValueError): store.review(ident['workspace'],candidate['id'],'publish',{'revision':1},backend.valid_refs)
    changed=store.review(ident['workspace'],candidate['id'],'edit',{'revision':1,'privacy_checked':True},backend.valid_refs)
    published=store.review(ident['workspace'],candidate['id'],'publish',{'revision':changed['revision']},backend.valid_refs)
    assert store.reuse(ident,'测试编号',[EID],backend.valid_refs)
    assert not store.reuse(ident,'测试编号',[],backend.valid_refs)
    backend.valid=False
    assert not store.reuse(ident,'测试编号',[EID],backend.valid_refs)
    backend.valid=True
    store.feedback(ident,'changed',r['answer_id'],'negative','步骤不完整')
    assert store.candidates(ident['workspace'])[0]['review_reason']=='步骤不完整'
    store.review(ident['workspace'],candidate['id'],'unpublish',{'revision':published['revision']},backend.valid_refs)
    assert not store.reuse(ident,'测试编号',[EID],backend.valid_refs)

def test_feedback_revision_and_unknown_feedback(env):
    r=run(env,'测试编号')
    ident,store,*_=env
    with pytest.raises(PermissionError): store.feedback(ident,'wrong',r['answer_id'],'positive',revision=2)
    store.feedback(ident,'unknown',r['answer_id'],'unknown')
    assert not store.candidates(ident['workspace'])

def test_model_outage_and_tool_loop_limit(env):
    assert '模型暂时不可用' in run(env,'__test_model_error__')['answer']
    r=run(env,'__test_loop__',options={'max_calls':2})
    assert r['call_count']==2 and '上限' in r['answer']

def test_timeout_releases_session_lock(env):
    r=run(env,'__test_timeout__',options={'timeout':1})
    assert r['status']=='timeout'
    assert '你好' in run(env,'你好')['answer']


def test_topic_switch_clears_pending_even_if_model_times_out(env):
    ident,store,*_=env
    store.session(ident)
    store.finish(ident,'pending-seed','测试编号','测试流程，需要截图吗？',[REF],
        {'kind':'images','source':REF,'expires_at':time.time()+600})
    assert run(env,'__test_timeout__',options={'timeout':1})['status']=='timeout'
    assert store.session(ident)['pending'] is None
    assert '请说明' in run(env,'需要')['answer']

def test_tool_errors_are_not_reported_as_no_evidence(env):
    async def broken(messages,state):
        if messages[-1]['role']=='tool': return {'content':'已经成功了','requires_evidence':False}
        return {'tool_calls':[{'id':'1','name':'delete_all','arguments':{}}]}
    r=run(env,'查资料',model=broken)
    assert '没有访问' in r['answer']


def test_mcp_rechecks_returned_document_scope(env):
    ident,store,backend,tools=env
    original=backend.search
    def injected(*args):
        value=original(*args)
        value['results'][0]['metadata']['entry_id']='unauthorized-document'
        return value
    backend.search=injected
    value=tools.call('search_knowledge',{'query':'@knowledge injected'},issue_scope(SECRET,ident,[EID],'scoped'))
    assert value['results']==[] and value['status']=='insufficient_evidence'


def test_unavailable_tool_is_distinct_from_no_evidence(env):
    class Unavailable(Backend):
        def search(self,*args):raise ConnectionError('synthetic outage')
    ident,store,_,_=env
    r=run((ident,store,env[2],ToolService(store,Unavailable(),SECRET)),'测试编号')
    assert '未成功完成' in r['answer'] and '没有足够证据' not in r['answer']


def test_current_turn_evidence_survives_sequential_history_tool(env):
    async def model(messages,state):
        if messages[-1]['role']!='tool':
            return {'tool_calls':[{'id':'knowledge','name':'search_knowledge','arguments':{'query':'测试编号'}}]}
        if messages[-1]['tool_call_id']=='knowledge':
            return {'tool_calls':[{'id':'history','name':'search_my_history','arguments':{'query':'测试编号'}}]}
        return {'content':'测试流程 [e1] 当前测试编号为 WRAG-TEST。','requires_evidence':True}
    result=run(env,'测试编号并核对历史',model=model)
    assert result['call_count']==2 and result['refs'][0]['entry_id']==EID and 'WRAG-TEST' in result['answer']


@pytest.mark.parametrize('with_evidence',[False,True])
def test_pi_limit_preserves_limit_notice_and_available_evidence(env,with_evidence):
    async def model(messages,state):
        transcript=messages+([{'role':'tool','tool_call_id':'pi1','content':json.dumps({
            'status':'ok','results':[{'content':'测试流程 e1 WRAG-TEST','metadata':{'result_type':'source_evidence'}}]})}] if with_evidence else [])
        return {'content':'工具上限','requires_evidence':True,'intent':'knowledge','_pi_limited':True,
                '_pi_state':{'refs':[REF] if with_evidence else [],'messages':transcript,
                             'tool_errors':[],'resource_requests':[],'call_count':1}}
    result=run(env,'测试编号',model=model)
    assert result['route']=='limited' and '上限' in result['answer']
    assert ('WRAG-TEST' in result['answer'])==with_evidence

def test_language_feedback_and_simulation_separation(env):
    r=run(env,'测试编号',options={'simulation':True})
    run(env,'这个方法解决了')
    ident,store,backend,_=env
    candidate=store.candidates(ident['workspace'])[0]
    assert candidate['simulation']
    store.review(ident['workspace'],candidate['id'],'edit',{'revision':1,'privacy_checked':True},backend.valid_refs)
    store.review(ident['workspace'],candidate['id'],'publish',{'revision':2},backend.valid_refs)
    assert store.reuse(ident,'测试编号',[EID],backend.valid_refs,True)
    assert not store.reuse(ident,'测试编号',[EID],backend.valid_refs,False)


def test_sdk_and_native_mcp_result_envelopes():
    from workrag_agent.transport import tool_result
    payload={'status':'ok','results':[{'content':'evidence'}]}
    assert tool_result([{'type':'text','text':json.dumps(payload)}])==payload
    assert tool_result({'structuredContent':None,'content':[{'type':'text','text':json.dumps(payload)}]})==payload
    assert tool_result({'isError':True})['status']=='tool_error'
    with pytest.raises(ValueError): tool_result([{'type':'text','text':'not JSON'}])


def test_interleaved_users_and_same_session_serialization(env):
    async def scenario():
        ident,store,backend,tools=env
        active=set(); peak=0
        async def model(messages,state):
            nonlocal peak
            actor=state['question']
            assert actor not in active
            active.add(actor);peak=max(peak,len(active))
            await asyncio.sleep(.05)
            active.remove(actor)
            return {'content':actor,'requires_evidence':False}
        async def tool(name,args): return tools.call(name,args,args['run_scope'])
        def workflow(actor):
            return Workflow(store,backend,model,tool,SECRET,{**ident,'sender':actor},str(uuid4()),[EID])
        rows=await asyncio.gather(workflow('alice').run('alice'),workflow('bob').run('bob'),workflow('alice').run('alice'))
        assert [r['answer'] for r in rows]==['alice','bob','alice']
        assert peak==2
        assert not store.search_history({**ident,'sender':'bob'},'alice')
    asyncio.run(scenario())


def test_90_day_cleanup_preserves_published_qa_and_recent_checkpoint(env):
    ident,store,backend,_=env
    result=run(env,'测试编号')
    store.feedback(ident,'retention-positive',result['answer_id'],'positive')
    candidate=store.candidates(ident['workspace'])[0]
    store.review(ident['workspace'],candidate['id'],'edit',{'revision':1,'privacy_checked':True},backend.valid_refs)
    store.review(ident['workspace'],candidate['id'],'publish',{'revision':2},backend.valid_refs)
    key=identity_key(ident)
    with store.connection() as c:
        c.execute("UPDATE wa_answers SET created_at=now()-interval '91 days' WHERE id=%s",(result['answer_id'],))
        # Active sessions must not retain older checkpoints indefinitely.
        c.execute("UPDATE checkpoints SET wa_created_at=now()-interval '91 days' WHERE thread_id=%s AND checkpoint_id<>(SELECT max(checkpoint_id) FROM checkpoints WHERE thread_id=%s)",(key,key))
    store.cleanup()
    assert not store.search_history(ident,'测试编号')
    assert store.reuse(ident,'测试编号',[EID],backend.valid_refs)
    with store.connection() as c:
        assert c.execute('SELECT count(*) AS n FROM checkpoints WHERE thread_id=%s',(key,)).fetchone()['n']==1


def test_retrieval_gate_queues_and_rejects_excess():
    import importlib.util
    import threading
    spec=importlib.util.spec_from_file_location('wa_admission',ROOT/'apps/backend/app/manuals/admission.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    gate=mod.RetrievalGate(max_pending=1); assert gate.acquire(False)
    waiting=threading.Event();done=[]
    def wait():
        waiting.set();ok=gate.acquire(timeout=2);done.append(ok)
        if ok: gate.release()
    thread=threading.Thread(target=wait);thread.start();waiting.wait()
    deadline=time.monotonic()+1
    while gate._slots._value and time.monotonic()<deadline:time.sleep(.01)
    rejected=[]
    excess=threading.Thread(target=lambda:rejected.append(gate.acquire(timeout=.1)))
    excess.start();excess.join();assert rejected==[False]
    gate.release();thread.join();assert done==[True]
