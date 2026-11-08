"""Verify real streaming, limits, grants, timeout and Pi restart on debug only."""
import copy
import json
import time
from uuid import uuid4
import httpx
from install_agent import RUNTIME,client,data
from local import wait_agent_ready
from pi_harness_service import start,stop


def verify():
    c=client();binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'))
    url='/api/v1/agents/'+binding['agent_id'];original=data(c.get(url))['agent']['config']
    assert original['runner_config'][original['runner']['id']]['engine']=='pi'
    prefix='pi-release-'+uuid4().hex[:10];checks=[];path=RUNTIME/'pi-release-acceptance.json'
    def save():path.write_text(json.dumps({'engine':'pi','real_model':True,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
    def record(name,**fields):
        checks.append({'name':name,'passed':True,**fields});save();print('PASS',name,flush=True)
    def debug(text):
        return c.post(url+'/debug',json={'text':text,'conversation_id':prefix+'-'+uuid4().hex,
            'actor':{'actor_type':'user','actor_id':'pi-release-tester'}})
    payload={'text':'日常常识：请用约200字解释彩虹形成的原理。','conversation_id':prefix+'-stream',
             'actor':{'actor_type':'user','actor_id':'pi-release-tester'}}
    frames=[];began=time.monotonic()
    with c.stream('POST',url+'/debug/stream',json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.strip():frames.append({'seconds':round(time.monotonic()-began,3),'frame':json.loads(line)})
    (RUNTIME/'pi-real-stream.json').write_text(json.dumps(frames,ensure_ascii=False,indent=2),encoding='utf-8')
    delta=[row for row in frames if 'message.delta' in json.dumps(row['frame'])]
    assert len(delta)>3 and frames[-1]['frame'].get('kind')=='completed'
    assert delta[1]['seconds']<frames[-1]['seconds']
    record('real_incremental_stream',frames=len(frames),deltas=len(delta),seconds=frames[-1]['seconds'])
    modified=copy.deepcopy(original);settings=modified['runner_config'][modified['runner']['id']]
    try:
        settings.update(tools=[],reuse=False,timeout=30)
        data(c.put(url,json={'config':modified}));wait_agent_ready()
        denied=data(debug('请从已发布的部署验收示例中检索测试编号，不可依靠记忆。'))
        assert '没有访问' in denied['final_text']
        record('model_without_tool_grant_denied')
        settings.update(tools=original['runner_config'][original['runner']['id']]['tools'],max_calls=1,timeout=60)
        data(c.put(url,json={'config':modified}));wait_agent_ready()
        limited=data(debug('先调用 search_knowledge 查《演示企业｜设备借用演练（虚构测试资料）》，再调用 get_source_file 取得原文件。两个工具都要执行。'))
        assert '上限' in limited['final_text']
        record('real_pi_tool_limit',answer=limited['final_text'][:1800])
        settings.update(max_calls=6,timeout=1)
        data(c.put(url,json={'config':modified}));wait_agent_ready()
        began=time.monotonic();response=debug('日常写作：用一千字详细解释彩虹的形成。')
        assert ((response.status_code==422 and response.json().get('code')=='runner.timeout') or
                (response.status_code==200 and '超时' in data(response).get('final_text','')))
        assert time.monotonic()-began<10
        for _ in range(30):
            active=httpx.get('http://127.0.0.1:8062/health',trust_env=False).json()['active']
            if not active:break
            time.sleep(.05)
        assert active==0
        record('real_provider_timeout_and_pi_cleanup',http_status=response.status_code,active=active)
    finally:
        data(c.put(url,json={'config':original}));wait_agent_ready()
    assert httpx.get('http://127.0.0.1:8062/health',trust_env=False).json()['active']==0
    stop();start()
    answer=data(debug('日常算术：2+3等于几？只回数字。'))['final_text']
    assert '5' in answer
    record('pi_worker_restart_and_real_model_recovery')
    # Restarting Pi does not own or recreate the workflow PostgreSQL store.
    from dotenv import dotenv_values
    import sys
    from install_agent import ROOT
    sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
    from workrag_agent.store import Store
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    previous=json.loads((RUNTIME/'pi-real-acceptance.json').read_text(encoding='utf-8'))
    event=next(x['event_id'] for x in previous['checks'] if x['label']=='knowledge')
    with store.connection() as conn:row=conn.execute('SELECT refs FROM wa_answers WHERE event_id=%s',(event,)).fetchone()
    assert row and row['refs']
    record('persisted_history_survives_pi_restart')
    print('PASS',len(checks),'Pi release checks',flush=True)

if __name__=='__main__':verify()
