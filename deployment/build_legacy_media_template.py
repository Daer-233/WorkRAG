"""Extend the official legacy LangBot template without replacing its states."""
import copy
import json
from install_agent import client,RUNTIME

def build():
    out=RUNTIME/'legacy-media-template';out.mkdir(exist_ok=True)
    response=client().get('/api/v1/platform/adapters/dingtalk/stream-card-template');response.raise_for_status()
    original=response.json();(out/'langbot-original.json').write_text(json.dumps(original,ensure_ascii=False,indent=2),encoding='utf-8')
    payload=copy.deepcopy(original);editor=json.loads(payload['editorData'])
    nodes=[]
    def walk(v):
        if isinstance(v,dict):
            if v.get('id'):nodes.append(v)
            for a in v.values():walk(a)
        elif isinstance(v,list):
            for a in v:walk(a)
    walk(editor['schema']['componentsTree'])
    panel=next(n for n in nodes if n.get('id')=='langbot_reasoning_3')
    image=next(n for n in nodes if n.get('id')=='langbot_logo')
    added=[]
    for content in [n for n in nodes if n.get('componentName')=='AICardContent' and any(c.get('id','').endswith('_answer') for c in n.get('children',[]))]:
        group=copy.deepcopy(panel);group['id']=content['id']+'_workrag_photos';props=group['props']
        props['id']['content']=group['id'];props['title']['content']='相关图片（点击展开）';props['contentVisible']=False
        props['visible']['variable']='workrag_has_images';group['children']=[]
        for i in range(3):
            node=copy.deepcopy(image);node['id']=group['id']+'_'+str(i);p=node['props']
            for key in ['images','darkModeImages']:
                p[key]['content']['zh_Hans']={'type':'dynamicImage','valueType':'variable','variable':f'workrag_image_{i}','variableType':'global','value':''}
            p['visible']=copy.deepcopy(props['visible']);p['visible']['variable']=f'workrag_image_visible_{i}'
            p['enablePreview']=True;p['height']['value']=180;p['width'].update(value=320,full=True,adaptive=True)
            p['scaleType']='fitCenter';p['marginTop']=8;p['marginBottom']=8
            group['children'].append(node)
        position=next(i for i,c in enumerate(content['children']) if c.get('id','').endswith('_answer'))+1
        content['children'].insert(position,group);added.append(group['id'])
    assert len(added)==3
    base=copy.deepcopy(editor['variableList'][0])
    for name in ['workrag_has_images',*[f'workrag_image_{i}' for i in range(3)],*[f'workrag_image_visible_{i}' for i in range(3)]]:
        var=copy.deepcopy(base);var.update(id=name,name=name,type='string');editor['variableList'].append(var)
    payload['editorData']=json.dumps(editor,ensure_ascii=False)
    target=out/'langbot-stream-with-folded-images.json';target.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    assert len(added)==len(set(added))
    (out/'status.json').write_text(json.dumps({'format':'legacy editorData','base':'official LangBot streaming template','folded_panels':added,'cloud_published':False,'native_client_verified':False},indent=2),encoding='utf-8')
    print('Prepared legacy template with 3 default-collapsed image panels; original streaming states preserved')
if __name__=='__main__':build()
