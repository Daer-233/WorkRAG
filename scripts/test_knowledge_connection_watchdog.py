import json
import httpx
from knowledge_connection_watchdog import Watchdog, State, decision, executions_active, failure_streak, read_active_executions, BOT


def bot(**changes):
    return {'enable':True,'adapter':'dingtalk-omni','adapter_config':{'fixture':'unchanged'},'event_bindings':[],**changes}


def errors(now=1000):
    return [{'text':'DingTalk: open connection failed','timestamp':now-60+10*i} for i in range(7)]


def test_only_sustained_fresh_failures_trigger():
    assert decision(bot(),[],State(),1000,80)=='no_sustained_failure'
    assert decision(bot(),errors()[:4],State(),1000,80)=='no_sustained_failure'
    assert decision(bot(),errors(800),State(),1000,80)=='no_sustained_failure'
    assert decision(bot(),errors(),State(),1000,80)=='check_executions'
    assert decision(bot(enable=False),errors(),State(),1000,80)=='disabled'
    assert decision(bot(),errors(),State(),1000,20)=='startup_grace'


def test_received_event_or_restart_resets_error_streak():
    for last in [{'text':'DingTalk event received: conversation=FriendMessage','timestamp':1000},
                 {'text':'DingTalk Omni adapter starting','timestamp':1000},
                 {'metadata':{'kind':'adapter_event_received'},'timestamp':1000}]:
        assert failure_streak(errors()+[last],1000)[0]==0


def test_cooldown_rate_limit_and_unknown_activity():
    assert decision(bot(),errors(),State(last_attempt=990),1000,80,active=False)=='cooldown'
    assert decision(bot(),errors(),State(attempts=[100,200,300]),1000,80,active=False)=='recovery_limit'
    assert decision(bot(),errors(),State(),1000,80,active=True)=='execution_busy_or_unknown'
    assert executions_active({'messages':[{'status':'running'}],'total':1})
    assert executions_active({'messages':[{'status':'success'}],'total':3})
    assert executions_active({'messages':[{}]})
    assert not executions_active({'messages':[{'status':'success'},{'status':'failed'}],'total':2})


def fixture(*, active=False, unavailable=False, timeout=False, clear=False, changed=False):
    requests=[];logs_calls=[];bot_calls=[];saves=[]
    def handler(request):
        requests.append(request)
        if request.method=='PUT':
            assert json.loads(request.content)=={'enable':True}
            if timeout: raise httpx.ReadTimeout('fixture',request=request)
            return httpx.Response(200,json={'data':{}})
        if request.url.path.endswith('/logs'):
            logs_calls.append(True)
            return httpx.Response(200,json={'data':{'logs':[] if clear and len(logs_calls)>1 else errors()}})
        if request.url.path.endswith('/messages'):
            if unavailable: return httpx.Response(403)
            return httpx.Response(200,json={'data':{'messages':[{'status':'running' if active else 'success'}],'total':1}})
        bot_calls.append(True)
        value=bot(adapter_config={'fixture':'edited'}) if changed and len(bot_calls)>1 else bot()
        return httpx.Response(200,json={'data':{'bot':value}})
    def decode(response): response.raise_for_status();return response.json()['data']
    client=httpx.Client(base_url='http://test',transport=httpx.MockTransport(handler))
    watcher=Watchdog(client,decode,clock=lambda:1000,save=lambda state:saves.append(state.outcome))
    watcher.started=900
    return watcher,requests,saves,client


def test_dry_run_does_not_mutate():
    watcher,requests,_,client=fixture()
    with client:
        assert watcher.check()['status']=='would_recover'
        assert all(r.method!='PUT' for r in requests)


def test_single_remount_preserves_configuration_and_persists_before_put():
    watcher,requests,saves,client=fixture()
    with client:
        assert watcher.check(recover=True)['status']=='remounted_waiting_for_connection'
        assert saves==['attempted','remounted_waiting_for_connection']
        assert watcher.check(recover=True)['status']=='cooldown'
        assert sum(r.method=='PUT' for r in requests)==1


def test_uncertain_remount_does_not_retry():
    watcher,requests,saves,client=fixture(timeout=True)
    with client:
        assert watcher.check(recover=True)['status']=='remount_unconfirmed_ReadTimeout'
        assert watcher.check(recover=True)['status']=='cooldown'
        assert sum(r.method=='PUT' for r in requests)==1
        assert saves[0]=='attempted'


def test_active_unknown_changed_or_recovered_skips_remount():
    for options,status in [({'active':True},'execution_busy_or_unknown'),
                           ({'unavailable':True},'execution_check_unavailable'),
                           ({'clear':True},'failure_cleared_or_bot_changed'),
                           ({'changed':True},'configuration_changed')]:
        watcher,requests,_,client=fixture(**options)
        with client:
            assert watcher.check(recover=True)['status']==status
            assert all(r.method!='PUT' for r in requests)


def test_paginated_history_does_not_permanently_disable_recovery():
    for busy in (False,True):
        offsets=[]
        def handler(request):
            offset=int(request.url.params['offset']);offsets.append(offset)
            rows=[{'status':'success'}]*(100 if offset==0 else 50)
            if offset and busy: rows[-1]={'status':'running'}
            return httpx.Response(200,json={'messages':rows,'total':150})
        with httpx.Client(base_url='http://test',transport=httpx.MockTransport(handler)) as client:
            assert read_active_executions(client,lambda response:response.json()) is busy
        assert offsets==[0,100]
