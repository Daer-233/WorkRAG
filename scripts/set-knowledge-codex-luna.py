"""Select Luna for this LangBot Pipeline only, with a narrow rollback."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

import httpx
from knowledge_connection_watchdog import connection, read_active_executions

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'data/manuals/runtime/luna-model-switch.private.json'
OVERRIDE=['-c','model="gpt-6-luna"','-c','model_reasoning_effort="high"']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    conn=connection()
    if not args.rollback:
        probe=json.loads((ROOT/'output/model-migration-luna-20261103/model-probe.json').read_text(encoding='utf-8'))
        assert probe.get('target_listed') and probe.get('resolved_target'), 'Target model compatibility unresolved'
    global_path=Path.home()/'.codex/config.toml'
    digest=hashlib.sha256(global_path.read_bytes()).hexdigest()
    with httpx.Client(base_url='http://127.0.0.1:5300',headers={'X-API-Key':conn.credential()},timeout=30) as client:
        if read_active_executions(client,conn.data):
            raise RuntimeError('Bot may be answering; defer changing its model')
        config=conn.data(client.get(f'/api/v1/pipelines/{conn.PIPELINE}'))['pipeline']['config']
        expected=deepcopy(config)
        runner=expected['ai']['runner_config'][conn.RUNNER]
        previous=runner.get('args-json','[]')
        if args.rollback:
            saved=json.loads(STATE.read_text(encoding='utf-8'))
            runner['args-json']=saved['previous_args_json']
        else:
            values=json.loads(previous)
            assert isinstance(values,list) and all(isinstance(v,str) for v in values)
            if values[-len(OVERRIDE):]==OVERRIDE:
                print('Pipeline already selects gpt-6-luna / high; no change.')
                return
            if STATE.exists(): raise RuntimeError('A previous switch record exists; inspect before replacing it')
            backup=ROOT/'data/manuals/runtime'/('pipeline-before-luna-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.private.json')
            backup.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
            STATE.write_text(json.dumps({'previous_args_json':previous,'backup':str(backup),
                'model':'gpt-6-luna','reasoning_effort':'high'},ensure_ascii=False,indent=2),encoding='utf-8')
            runner['args-json']=json.dumps(values+OVERRIDE)
        conn.data(client.put(f'/api/v1/pipelines/{conn.PIPELINE}',json={'config':expected}))
        actual=conn.data(client.get(f'/api/v1/pipelines/{conn.PIPELINE}'))['pipeline']['config']
        assert actual==expected, 'Saved model override differs from expected'
        actual=deepcopy(actual)
        actual['ai']['runner_config'][conn.RUNNER]['args-json']=previous
        assert actual==config, 'Unexpected non-model configuration changes'
        assert hashlib.sha256(global_path.read_bytes()).hexdigest()==digest, 'Global Codex configuration changed'
    print(json.dumps({'status':'rolled_back' if args.rollback else 'switched',
        'model':None if args.rollback else 'gpt-6-luna','reasoning_effort':None if args.rollback else 'high',
        'global_config_unchanged':True,'retrieval_permissions_and_bot_routes_unchanged':True}))


if __name__=='__main__':main()
