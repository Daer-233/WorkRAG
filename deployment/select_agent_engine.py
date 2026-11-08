"""Select Pi or legacy per processor; preserves all other processor settings."""
import argparse
import copy
import json
import time
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,client,data
from local import wait_agent_ready

def select(engine,target):
    binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'));c=client()
    if engine=='pi':
        from pi_harness_service import start,config
        start();private=dotenv_values(ROOT/'data/manuals/runtime/agent.env')
        data(c.put('/api/v1/plugins/workrag/WorkRAGGraph/config',json={
            'database_dsn':private['WORKRAG_AGENT_DSN'].replace('@127.0.0.1:','@postgres:'),
            'scope_secret':private['WORKRAG_SCOPE_SECRET'],'workspace':binding['workspace'],
            'pi_harness_url':'ws://host.docker.internal:8062/run','pi_harness_token':config()['token']}))
        wait_agent_ready()
    records={};updates=[]
    for kind in (['debug','pipeline'] if target=='both' else [target]):
        pipeline=kind=='pipeline';url='/api/v1/'+('pipelines/'+binding['pipeline_id'] if pipeline else 'agents/'+binding['agent_id'])
        row=data(c.get(url))['pipeline' if pipeline else 'agent'];cfg=copy.deepcopy(row['config']);records[kind]=row['config']
        node=cfg['ai'] if pipeline else cfg;runner=node['runner']['id'];node['runner_config'][runner]['engine']=engine
        updates.append((url,pipeline,cfg))
    # Save the exact processor settings before the first mutation.
    (RUNTIME/('engine-backup-'+str(time.time_ns())+'.private.json')).write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    for url,pipeline,cfg in updates:
        data(c.put(url,json={'config':cfg}))
        current=data(c.get(url))['pipeline' if pipeline else 'agent']['config'];node=current['ai'] if pipeline else current
        assert node['runner_config'][node['runner']['id']]['engine']==engine
    wait_agent_ready()
    print('Selected',engine,'for',target)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('engine',choices=['pi','legacy']);parser.add_argument('--target',choices=['debug','pipeline','both'],default='debug')
    args=parser.parse_args();select(args.engine,args.target)
