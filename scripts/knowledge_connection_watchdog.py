"""Watch one authorized DingTalk bot; recover only a fresh, sustained failure.

No proactive messages, credential changes, model restarts or query retries.
Unknown/busy execution state always prevents a connection remount.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import importlib.util
import json
import os
from pathlib import Path
import time

import httpx

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'data/manuals/runtime/connection-watchdog'
BOT='9777ca2e-7df1-4441-84ca-abedd4bc5c01'
BASE='http://127.0.0.1:5300'
TERMINAL={'success','failed','error','cancelled','canceled','dropped','completed','skipped','interrupted'}
FAILURES=('DingTalk: open connection failed','DingTalk: connection closed','DingTalk: unknown exception')


@dataclass
class State:
    last_attempt: float = 0
    attempts: list[float] = field(default_factory=list)
    outcome: str = ''


def failure_streak(logs, now):
    failures=[]
    for log in reversed(logs):
        stamp=log.get('timestamp',0)
        if not isinstance(stamp,(int,float)) or stamp>now+5:
            continue
        text=str(log.get('text',''))
        meta=log.get('metadata') or {}
        if text=='DingTalk Omni adapter starting' or text.startswith('DingTalk event received:') or meta.get('kind')=='adapter_event_received':
            break
        if text.startswith(FAILURES):
            failures.append(stamp)
    recent=[t for t in failures if now-180<=t<=now+5]
    fresh=bool(recent and now-max(recent)<=60)
    span=max(recent)-min(recent) if recent else 0
    return len(recent),span,fresh


def decision(bot, logs, state, now, uptime, *, active=None):
    if bot.get('enable') is not True: return 'disabled'
    if bot.get('adapter')!='dingtalk-omni': return 'unexpected_adapter'
    if uptime<60: return 'startup_grace'
    count,span,fresh=failure_streak(logs,now)
    if count<6 or span<45 or not fresh: return 'no_sustained_failure'
    if state.last_attempt and now-state.last_attempt<600: return 'cooldown'
    if sum(now-3600<t<=now+5 for t in state.attempts)>=3: return 'recovery_limit'
    if active is None: return 'check_executions'
    if active: return 'execution_busy_or_unknown'
    return 'recover'


def executions_active(data):
    rows=data.get('messages')
    # A bounded result must cover all selected records to establish idle.
    if not isinstance(rows,list) or data.get('total',len(rows))>len(rows): return True
    return any(str(row.get('status','')).casefold() not in TERMINAL for row in rows)


def read_active_executions(client,decode):
    # Paginate rather than treating a normal history of >100 rows as busy.
    # Retain no message text; fail closed if the bounded scan cannot finish.
    offset=0
    while offset<5000:
        data=decode(client.get('/api/v1/monitoring/messages',params={'botId':BOT,'limit':250,'offset':offset}))
        rows=data.get('messages')
        if not isinstance(rows,list): return True
        if any(str(row.get('status','')).casefold() not in TERMINAL for row in rows): return True
        offset+=len(rows)
        if offset>=data.get('total',offset): return False
        if not rows: return True
    return True


def connection():
    spec=importlib.util.spec_from_file_location('watchdog_connection',ROOT/'scripts/connect-langbot-knowledge.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def atomic_json(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


class Watchdog:
    def __init__(self, client, decode, *, state=None, save=None, clock=time.time):
        self.client=client;self.decode=decode;self.state=state or State()
        self.save=save or (lambda state:None);self.clock=clock
        self.started=clock()

    def check(self, *, recover=False):
        now=self.clock()
        bot=self.decode(self.client.get(f'/api/v1/platform/bots/{BOT}'))['bot']
        if bot.get('enable') is not True:
            return {'status':'disabled'}
        logs=self.decode(self.client.post(f'/api/v1/platform/bots/{BOT}/logs',json={'from_index':-1,'max_count':40}))['logs']
        action=decision(bot,logs,self.state,now,now-self.started)
        count,span,fresh=failure_streak(logs,now)
        report={'status':action,'recent_failure_count':count,'failure_span_seconds':span,'fresh_failure':fresh}
        if action!='check_executions': return report
        try:
            active=read_active_executions(self.client,self.decode)
        except Exception:
            return {**report,'status':'execution_check_unavailable'}
        action=decision(bot,logs,self.state,now,now-self.started,active=active)
        if action!='recover' or not recover:
            return {**report,'status':action if action!='recover' else 'would_recover'}
        # Re-read the latest configuration/failures immediately before mutation.
        current=self.decode(self.client.get(f'/api/v1/platform/bots/{BOT}'))['bot']
        latest=self.decode(self.client.post(f'/api/v1/platform/bots/{BOT}/logs',json={'from_index':-1,'max_count':40}))['logs']
        if current.get('adapter_config')!=bot.get('adapter_config') or current.get('event_bindings')!=bot.get('event_bindings'):
            return {**report,'status':'configuration_changed'}
        if decision(current,latest,self.state,self.clock(),self.clock()-self.started,active=active)!='recover':
            return {**report,'status':'failure_cleared_or_bot_changed'}
        # Persist BEFORE PUT: an uncertain network response cannot cause a quick
        # second remount. No mutation is retried automatically in this cycle.
        self.state.last_attempt=now
        self.state.attempts=[t for t in self.state.attempts if t>now-3600]+[now]
        self.state.outcome='attempted'
        self.save(self.state)
        try:
            self.decode(self.client.put(f'/api/v1/platform/bots/{BOT}',json={'enable':True}))
            self.state.outcome='remounted_waiting_for_connection'
        except Exception as exc:
            self.state.outcome='remount_unconfirmed_'+type(exc).__name__
        self.save(self.state)
        return {**report,'status':self.state.outcome}


def single_process(file):
    # Hold this descriptor for the entire process lifetime, including API waits.
    file.parent.mkdir(parents=True,exist_ok=True)
    handle=file.open('a+b');handle.seek(0)
    if not handle.read(1): handle.write(b'1');handle.flush()
    handle.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    return handle


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--recover',action='store_true')
    args=parser.parse_args()
    RUNTIME.mkdir(parents=True,exist_ok=True)
    guard=single_process(RUNTIME/'watchdog.lock')
    state_path=RUNTIME/'state.json'
    state=State(**json.loads(state_path.read_text(encoding='utf-8'))) if state_path.exists() else State()
    conn=connection()
    last=None
    with guard, httpx.Client(base_url=BASE,headers={'X-API-Key':conn.credential()},timeout=20) as client:
        watchdog=Watchdog(client,conn.data,state=state,save=lambda state:atomic_json(state_path,asdict(state)))
        if not args.serve: watchdog.started-=60
        while True:
            try:
                report=watchdog.check(recover=args.recover)
            except Exception as exc:
                # Do not print exceptions containing response bodies or headers.
                report={'status':'check_unavailable','error_type':type(exc).__name__}
            report['checked_at_epoch']=int(time.time())
            report['automatic_recovery_enabled']=args.recover
            atomic_json(RUNTIME/'status.json',report)
            label=report['status']
            if label!=last or not args.serve:
                print(json.dumps(report),flush=True);last=label
            if not args.serve: break
            time.sleep(30)


if __name__=='__main__':main()
