"""Real provider acceptance through LangBot; only synthetic local data is queried."""

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

sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
from workrag_agent.store import Store

def verify():
    c=client();binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'))
    aid=binding['agent_id'];agent=data(c.get('/api/v1/agents/'+aid))['agent'];config=agent['config']
    settings=config['runner_config'][config['runner']['id']]
    if settings.get('simulation') or not settings.get('model'):raise ValueError('A real selected model with simulation disabled is required')
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    prefix='real-'+uuid4().hex[:10];records=[]
    report={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'model_uuid':settings['model'],'model_name':binding.get('model_name'),
        'simulation':False,'scope':'LangBot debug and local synthetic sample only; no real bot delivery','checks':records}
    path=RUNTIME/'real-llm-acceptance.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def debug(label,text,conversation=None,user='real-model-alice'):
        started=time.monotonic()
        result=data(c.post('/api/v1/agents/'+aid+'/debug',json={'text':text,'conversation_id':conversation or prefix,
                     'actor':{'actor_type':'user','actor_id':user}}))
        with store.connection() as conn:row=conn.execute('SELECT * FROM wa_answers WHERE event_id=%s',(result['event_id'],)).fetchone()
        if not row:raise AssertionError(label+': answer was not persisted')
        with PostgresSaver.from_conn_string(store.dsn) as saver:
            state=saver.get_tuple({'configurable':{'thread_id':row['session_key']}}).checkpoint['channel_values']
        used=[tc['function']['name'] for m in state.get('messages',[]) for tc in m.get('tool_calls',[])]
        if state.get('route')=='followup_done':used.extend(tc['name'] for tc in state.get('calls',[]))
        record={'name':label,'question':text,'answer':result.get('final_text'),'elapsed_seconds':round(time.monotonic()-started,2),
            'event_id':result['event_id'],'answer_id':str(row['id']),'intent':state.get('intent'),'route':state.get('route'),
            'tool_calls':used,'call_count':state.get('call_count'),'refs':row['refs'],'simulation':row['simulation'],
            'output_events':[e['type'] for e in result.get('execution_events',[])]}
        records.append(record);save()
        assert not row['simulation'] and '【模拟模型验收】' not in result['final_text']
        assert '<think>' not in result['final_text']
        assert '模型暂时不可用' not in result['final_text'],label+': model error'
        print('RESULT',label,'seconds',record['elapsed_seconds'],'intent',record['intent'],'tools',used,flush=True)
        print(result['final_text'][:500],flush=True)
        return record
    hello=debug('greeting','你好。请用一句简短的中文介绍你能做什么。',prefix+'-hello')
    assert hello['intent']=='daily' and not hello['tool_calls'] and '没有足够证据' not in hello['answer']
    hello['passed']=True;save()
    calc=debug('daily_question','日常算术题：1加1等于多少？只回复数字。',prefix+'-daily')
    assert calc['intent']=='daily' and '2' in calc['answer'];calc['passed']=True;save()
    knowledge=debug('grounded_knowledge','请检索已发布的《部署验收示例（非真实业务制度）》，告诉我部署验收测试编号。引用资料标题、版本与证据ID，回答不超过120字。')
    assert 'WRAG-LOCAL-20261107' in knowledge['answer'] and knowledge['refs'] and 'search_knowledge' in knowledge['tool_calls']
    assert all(r['entry_id']==binding['sample_entry_id'] for r in knowledge['refs'])
    knowledge['passed']=True;save()
    file=debug('source_file_followup','需要原文件')
    assert 'get_source_file' in file['tool_calls'] and 'deployment-smoke.docx' in file['answer'];file['passed']=True;save()
    image=debug('image_followup_without_images','需要截图')
    assert 'get_document_images' in image['tool_calls'] and '已发送' not in image['answer'];image['passed']=True;save()
    ambiguous=debug('other_user_ambiguous_confirmation','需要',user='real-model-bob')
    assert '请说明' in ambiguous['answer'] and not ambiguous['refs'];ambiguous['passed']=True;save()
    missing=debug('no_evidence','请查询已发布的公司制度：火星出差的每日住宿补贴是多少元？没有依据就明确说明，不提供通用建议。',prefix+'-missing')
    assert any(w in missing['answer'] for w in ['没有','未找到','无法','未提供','不足','不包含','未明确'])
    missing['passed']=True;save()
    combined=debug('knowledge_evidence_survives_sequential_history',
        '先检索已发布的部署验收示例取得测试编号，然后用刚查到的编号作为个人历史查询关键词，核对我以前是否问过。最后给出当前资料编号和证据ID。',prefix+'-combined')
    assert 'search_knowledge' in combined['tool_calls'] and 'search_my_history' in combined['tool_calls']
    assert combined['refs'] and 'WRAG-LOCAL-20261107' in combined['answer']
    combined['passed']=True;save()
    history=debug('personal_history','请调用个人历史工具，查找我之前问过的部署验收测试编号，只据我的历史回答。',prefix+'-history')
    assert 'search_my_history' in history['tool_calls'] and 'WRAG-LOCAL-20261107' in history['answer'];history['passed']=True;save()
    other=debug('other_user_history_isolation','仅查我自己的聊天历史：我之前问过部署验收测试编号吗？不要查询知识库。',prefix+'-bob-history',user='real-model-bob')
    assert 'search_my_history' in other['tool_calls'] and 'WRAG-LOCAL-20261107' not in other['answer']
    other['passed']=True;save()
    started=time.monotonic()
    pipeline=data(c.post('/api/v1/pipelines/'+binding['pipeline_id']+'/run',json={
        'message':'请检索部署验收示例，给出测试编号，并引用资料标题和证据ID。'}))
    assert pipeline['status']=='completed' and 'WRAG-LOCAL-20261107' in pipeline['reply'] and '【模拟模型验收】' not in pipeline['reply']
    records.append({'name':'pipeline_real_model_and_tools','passed':True,'answer':pipeline['reply'],
        'elapsed_seconds':round(time.monotonic()-started,2)});save();print('PASS real pipeline',flush=True)
    payload={'text':'日常常识题：用两句话解释白天的天空为什么通常呈蓝色，不涉及公司资料。',
        'conversation_id':prefix+'-stream','actor':{'actor_type':'user','actor_id':'real-model-alice'}}
    started=time.monotonic();frames=[]
    with c.stream('POST','/api/v1/agents/'+aid+'/debug/stream',json=payload) as response:
        response.raise_for_status();assert 'application/x-ndjson' in response.headers.get('content-type','')
        for line in response.iter_lines():
            if line.strip():
                try:frames.append(json.loads(line))
                except json.JSONDecodeError:pass
    raw=json.dumps(frames,ensure_ascii=False)
    assert 'message.delta' in raw and 'run.completed' in raw
    (RUNTIME/'real-llm-stream.json').write_text(json.dumps(frames,ensure_ascii=False,indent=2),encoding='utf-8')
    assert frames[-1].get('kind')=='completed' and '<think>' not in frames[-1]['data'].get('final_text','')
    records.append({'name':'ndjson_stream_with_validated_deltas','passed':True,'frames':len(frames),'protocol':'application/x-ndjson',
        'delivery':'validated answer chunks, not unverified live tokens',
        'elapsed_seconds':round(time.monotonic()-started,2)});save();print('PASS real NDJSON output',flush=True)
    import copy
    import local
    import psutil
    original=data(c.get('/api/v1/agents/'+aid))['agent']['config']
    modified=copy.deepcopy(original);rid=modified['runner']['id'];opts=modified['runner_config'][rid]
    try:
        opts.update(tools=[],reuse=False,timeout=30)
        data(c.put('/api/v1/agents/'+aid,json={'config':modified}))
        denied=debug('real_model_tool_grant_denied','请检索已发布的部署验收示例并给出测试编号。',prefix+'-denied')
        assert '没有访问' in denied['answer'] and not denied['refs'];denied['passed']=True;save()
        opts.update(tools=settings['tools'],max_calls=1,timeout=60)
        data(c.put('/api/v1/agents/'+aid,json={'config':modified}))
        limited=debug('real_model_tool_call_limit',
            '请先调用 search_knowledge 检索部署验收示例，再调用 get_source_file 获取其原文件引用。我明确需要原文件，两个工具都要调用。',prefix+'-limit')
        assert '上限' in limited['answer'] and limited['call_count']==1;limited['passed']=True;save()
        opts.update(max_calls=6,timeout=1)
        data(c.put('/api/v1/agents/'+aid,json={'config':modified}))
        started=time.monotonic()
        response=c.post('/api/v1/agents/'+aid+'/debug',json={'text':'日常写作：用一千字分段解释彩虹的形成原理。',
            'conversation_id':prefix+'-timeout','actor':{'actor_type':'user','actor_id':'real-model-alice'}})
        timeout_ok=(response.status_code==422 and response.json().get('code')=='runner.timeout') or (
            response.status_code==200 and '超时' in data(response).get('final_text',''))
        assert timeout_ok and time.monotonic()-started<10
        records.append({'name':'real_provider_deadline_cancellation','passed':True,'http_status':response.status_code,
            'elapsed_seconds':round(time.monotonic()-started,2)});save();print('PASS real provider timeout cancellation',flush=True)
    finally:data(c.put('/api/v1/agents/'+aid,json={'config':original}))
    backend=local.process('backend')
    if not backend:raise RuntimeError('Cannot identify the owned backend process for fault-injection test')
    owned=backend.children(recursive=True)+[backend]
    try:
        print('Temporarily stopping owned backend for the real tool-failure test',flush=True)
        for process in owned:
            try:process.terminate()
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(owned,timeout=10)
        if alive:raise RuntimeError('Backend did not stop for controlled failure test')
        failed=debug('real_mcp_backend_failure','请通过知识库工具检索部署验收示例中的测试编号，不依赖历史记忆。',prefix+'-tool-failure')
        assert '未成功完成' in failed['answer'] and failed['call_count']>0 and not failed['refs']
        failed['passed']=True;save()
    finally:local.start()
    recovered=debug('real_model_and_mcp_recovery','请重新检索部署验收示例的测试编号，引用资料标题和证据ID。',prefix+'-recovery')
    assert 'WRAG-LOCAL-20261107' in recovered['answer'] and 'search_knowledge' in recovered['tool_calls']
    recovered['passed']=True;save()
    report['passed']=all(x.get('passed') for x in records);save()
    binding['real_llm_verified']=True
    (RUNTIME/'binding.json').write_text(json.dumps(binding,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS real model acceptance:',len(records),'checks',flush=True)

if __name__=='__main__':verify()
