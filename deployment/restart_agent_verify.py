"""Restart this local deployment and verify durable state; no real bot delivery."""
import hashlib
import json
import sys
import time
import yaml
from dotenv import dotenv_values
from install_agent import ROOT,RUNTIME,CONFIG,client,data
import local

sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
from workrag_agent.store import Store
from workrag_agent.tools import Backend

def restart_verify():
    binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'))
    store=Store(dotenv_values(ROOT/'data/manuals/runtime/agent.env')['WORKRAG_AGENT_DSN'])
    def snapshot():
        with store.connection() as c:
            return {table:c.execute('SELECT count(*) AS n FROM '+table).fetchone()['n']
                    for table in ['wa_answers','wa_candidates','wa_feedback','wa_feedback_events','checkpoints']}
    def original():
        response=client().get('/api/v1/pipelines/9140e5df-003f-40eb-846b-c08538b28891')
        change_file=RUNTIME/'post-acceptance-changes.json'
        if response.status_code==404 and change_file.exists() and json.loads(change_file.read_text(encoding='utf-8')).get('user_confirmed_removal') is True:
            return 'removed-by-user'
        cfg=data(response)['pipeline']['config']
        return hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
    before=snapshot(); original_before=original()
    # These credentials are now private plugin configuration, never worker-global env.
    config_path=local.Path(CONFIG); config=yaml.safe_load(config_path.read_text(encoding='utf-8'))
    if config['services']['langbot_plugin_runtime'].get('env_file')==['./agent.env']:
        (RUNTIME/'compose-before-agent-cleanup.yaml').write_text(config_path.read_text(encoding='utf-8'),encoding='utf-8')
        del config['services']['langbot_plugin_runtime']['env_file']
        config_path.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
    local.stop();local.start()
    c=client()
    for _ in range(60):
        try:
            tools=data(c.get('/api/v1/agents/_/metadata'))['host_tools']
            if len([t for t in tools if t.get('source_id')==binding['mcp_server_id']])==4:break
        except Exception:pass
        time.sleep(1)
    else:raise RuntimeError('WorkRAG MCP did not reconnect after restart')
    after=snapshot();assert before==after,(before,after)
    assert original_before==original(),'Original Local Agent changed'
    result=data(c.post('/api/v1/agents/'+binding['agent_id']+'/debug',json={'text':'部署验收测试编号是什么（重启复验 '+str(time.time_ns())+'）',
          'conversation_id':'restart-'+str(time.time_ns()),'actor':{'actor_type':'user','actor_id':'restart-verifier'}}))
    assert 'WRAG-LOCAL-20261107' in result['final_text']
    assert Backend().document(binding['sample_entry_id'])['status']=='published'
    report={'time':time.strftime('%Y-%m-%d %H:%M:%S'),'before':before,'after':after,
        'durable_state':True,'mcp_reconnected':True,'original_local_agent_unchanged':True,'knowledge_after_restart':True,
        'original_removed_by_user':original_before=='removed-by-user'}
    (RUNTIME/'restart-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS full service restart, durable agent state, MCP reconnect, original Local Agent and knowledge retrieval')

if __name__=='__main__':restart_verify()
