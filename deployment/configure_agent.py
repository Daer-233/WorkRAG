"""Configure only the new plugin and independent pilot processor."""
import json
from pathlib import Path
import time
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,client,data
from entry_names import AGENT_NAME,PIPELINE_NAME,MCP_NAME,resolve_mcp_server
from urllib.parse import quote

RUNNER='plugin:workrag/WorkRAGGraph/workrag'
def configure():
    c=client()
    existing=data(c.get('/api/v1/agents'))['agents']
    previous=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8')) if (RUNTIME/'binding.json').exists() else {}
    workspace=data(c.get('/api/v1/pipelines'))['pipelines'][0]['workspace_uuid']
    private=dotenv_values(ROOT/'data/manuals/runtime/agent.env')
    settings={'database_dsn':private['WORKRAG_AGENT_DSN'].replace('@127.0.0.1:','@postgres:'),
              'scope_secret':private['WORKRAG_SCOPE_SECRET'],'workspace':workspace}
    data(c.put('/api/v1/plugins/workrag/WorkRAGGraph/config',json=settings))
    for _ in range(60):
        metadata=data(c.get('/api/v1/agents/_/metadata'))
        if RUNNER in json.dumps(metadata): break
        time.sleep(1)
    else: raise RuntimeError('Runner did not become available after configuration')
    servers=data(c.get('/api/v1/mcp/servers'))['servers']
    server=resolve_mcp_server(servers)
    server_settings={'name':server['name'] if server else MCP_NAME,'mode':'remote','enable':True,'extra_args':{
        'url':'http://host.docker.internal:8061/mcp','headers':{'Authorization':'Bearer '+private['WORKRAG_MCP_ACCESS_TOKEN']}}}
    if not server:
        sid=data(c.post('/api/v1/mcp/servers',json=server_settings))['uuid']
    else:
        sid=server['uuid']; data(c.put('/api/v1/mcp/servers/'+quote(server['name'],safe=''),json=server_settings))
    entry=json.loads((ROOT/'data/manuals/runtime/acceptance.json').read_text(encoding='utf-8'))['sample']['entry_id']
    for _ in range(60):
        catalog=data(c.get('/api/v1/agents/_/metadata'))['host_tools']
        tool_names=[t['name'] for t in catalog if t.get('source')=='mcp' and t.get('source_id')==sid]
        if len(tool_names)==4: break
        time.sleep(1)
    if len(tool_names)!=4: raise RuntimeError('Expected exactly four connected WorkRAG tools; retry after MCP connects')
    config={'model':'','prompt':'依据已发布资料回答问题，保留来源。','simulation':True,'reuse':True,
            'allowed_entry_ids':json.dumps([entry]),'tools':tool_names,
            'enable-all-tools':False,'timeout':180,'max_calls':6,'top_k':5}
    # Source selection is declared in the manifest to preserve Host authorization.
    pilot=next((a for a in existing if a['uuid']==previous.get('agent_id') or a.get('name') in (AGENT_NAME,'工作知识助手 · 本机验收')),None)
    if pilot:config.update(pilot.get('config',{}).get('runner_config',{}).get(RUNNER,{}))
    container={'runner':{'id':RUNNER},'runner_config':{RUNNER:config}}
    if not pilot:
        aid=data(c.post('/api/v1/agents',json={'name':AGENT_NAME,'kind':'agent',
            'description':'独立 LangGraph 验收处理器；模拟模式；不绑定真实机器人。',
            'supported_event_patterns':['message.received','feedback.received'],'config':container}))['uuid']
    else:
        aid=pilot['uuid']; data(c.put('/api/v1/agents/'+aid,json={'config':container,'supported_event_patterns':['message.received','feedback.received']}))
    pipelines=data(c.get('/api/v1/pipelines'))['pipelines']
    pipeline=next((p for p in pipelines if p['uuid']==previous.get('pipeline_id') or p['name'] in (PIPELINE_NAME,'工作知识助手 · 流水线验收')),None)
    if pipeline is None:
        pid=data(c.post('/api/v1/agents',json={'kind':'pipeline','name':PIPELINE_NAME}))['uuid']
        pipeline=data(c.get('/api/v1/pipelines/'+pid))['pipeline']
    else: pid=pipeline['uuid']
    pipeline_config=pipeline['config']; pipeline_config['ai']['runner']={'id':RUNNER}
    pipeline_config['ai'].setdefault('runner_config',{}).setdefault(RUNNER,config)
    data(c.put('/api/v1/pipelines/'+pid,json={'config':pipeline_config}))
    report={**previous,'plugin':'workrag/WorkRAGGraph','runner':RUNNER,'agent_id':aid,'workspace':workspace,
            'mcp_server_id':sid,'pipeline_id':pid,'sample_entry_id':entry,'simulation':bool(config.get('simulation')),
            'real_llm_verified':previous.get('real_llm_verified',False)}
    RUNTIME.mkdir(parents=True,exist_ok=True)
    (RUNTIME/'binding.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': configure()
