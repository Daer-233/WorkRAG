"""Final local pipeline acceptance; does not deliver DingTalk messages."""
import json
import subprocess
import time
from install_agent import RUNTIME,DOCKER,client,data


def verify():
    c=client();binding=json.loads((RUNTIME/'binding.json').read_text(encoding='utf-8'))
    selected={}
    for kind,url,key in [('debug','agents/'+binding['agent_id'],'agent'),('pipeline','pipelines/'+binding['pipeline_id'],'pipeline')]:
        cfg=data(c.get('/api/v1/'+url))[key]['config'];node=cfg['ai'] if kind=='pipeline' else cfg
        settings=node['runner_config'][node['runner']['id']]
        assert settings['engine']=='pi' and settings['simulation'] is False
        selected[kind]={'engine':settings['engine'],'model_uuid':settings['model'],'simulation':False}
    plugins=data(c.get('/api/v1/plugins'))['plugins']
    plugin=next(p for p in plugins if p.get('manifest',{}).get('manifest',{}).get('metadata',{}).get('name')=='WorkRAGGraph')
    version=plugin['manifest']['manifest']['metadata']['version']
    assert version=='0.4.2' and plugin['status']=='initialized'
    began=time.monotonic()
    result=data(c.post('/api/v1/pipelines/'+binding['pipeline_id']+'/run',json={
        'message':'《演示企业｜设备借用演练（虚构测试资料）》第二步怎么做，要核对什么设备编号？'}))
    assert result['status']=='completed' and 'DEMO-LAPTOP-008' in result['reply']
    assert 'demo-v1' not in result['reply'] and '证据 ID' not in result['reply']
    raw=subprocess.check_output([DOCKER,'exec','workrag-langbot-1','cat','/app/data/workrag-legacy-media-config.json'],text=True,encoding='utf-8')
    media=json.loads(raw)
    assert media['folded_template_published'] and media['answer_streaming_component']
    raw=subprocess.check_output([DOCKER,'exec','workrag-langbot-1','cat','/app/data/workrag-a2ui-config.json'],text=True,encoding='utf-8')
    assert json.loads(raw)['enabled'] is False
    report={'version':version,'selected':selected,'pipeline_passed':True,'seconds':round(time.monotonic()-began,2),
        'answer':result['reply'],'legacy_folded_images_enabled':True,'legacy_answer_compatibility_enabled':True,
        'a2ui_enabled':False,'dingTalk_delivery_this_test':False}
    (RUNTIME/'pi-pipeline-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS Pi debug + production pipeline; legacy card settings preserved; no DingTalk delivery',flush=True)

if __name__=='__main__':verify()
