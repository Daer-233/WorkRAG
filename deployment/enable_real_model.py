"""Select the user's existing model via UUID without reading provider secrets."""
import argparse
import copy
import json
import time
from install_agent import client,data,RUNTIME
from local import wait_agent_ready

def enable(model_uuid):
    c=client(); binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'))
    models=data(c.get('/api/v1/provider/models/llm',params={'include_secret':'false'}))['models']
    model=next((m for m in models if m['uuid']==model_uuid),None)
    if not model or 'func_call' not in model.get('abilities',[]):
        raise ValueError('Selected model is unavailable or does not declare tool calling')
    agent_url='/api/v1/agents/'+binding['agent_id']; pipeline_url='/api/v1/pipelines/'+binding['pipeline_id']
    agent=data(c.get(agent_url))['agent']; pipeline=data(c.get(pipeline_url))['pipeline']
    backup=RUNTIME/('before-real-model-'+str(time.time_ns())+'.json')
    backup.write_text(json.dumps({'agent_config':agent['config'],'pipeline_config':pipeline['config']},ensure_ascii=False,indent=2),encoding='utf-8')
    config=copy.deepcopy(agent['config']); runner=config['runner']['id']
    config['runner_config'][runner].update(model=model_uuid,simulation=False)
    pconfig=copy.deepcopy(pipeline['config']); prunner=pconfig['ai']['runner']['id']
    pconfig['ai']['runner_config'][prunner].update(model=model_uuid,simulation=False)
    data(c.put(agent_url,json={'config':config}))
    data(c.put(pipeline_url,json={'config':pconfig}))
    wait_agent_ready()
    for path,field in [(agent_url,'agent'),(pipeline_url,'pipeline')]:
        current=data(c.get(path))[field]['config']
        if field=='pipeline':current=current['ai']
        selected=current['runner_config'][current['runner']['id']]
        assert selected['model']==model_uuid and selected['simulation'] is False
    binding.update(model_uuid=model_uuid,model_name=model['name'],simulation=False,real_llm_verified=False)
    (RUNTIME/'binding.json').write_text(json.dumps(binding,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Selected existing model:',model['name'],'; simulation disabled for both processors')
    print('Previous processor configurations saved locally')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('model_uuid');enable(parser.parse_args().model_uuid)
