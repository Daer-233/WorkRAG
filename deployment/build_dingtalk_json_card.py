"""Build a DingTalk A2UI v1.0 card using the official public catalog.

This is a JSON-building asset, not the legacy editorData template export.
It never publishes, changes a bot binding, or sends a message.
"""
import json
import shutil

from install_agent import ROOT,RUNTIME

CATALOG='https://dingtalk.com/card/a2ui/catalogs/public/catalog.json'
SURFACE='workrag-knowledge-card-v2'
OUT=RUNTIME/'card-json-v2'


def binding(path):return {'path':path}


def event(name,**context):
    return {'event':{'name':name,'context':{'answer_id':binding('/answer_id'),
        'document_id':binding('/document/id'),'document_version':binding('/document/version'),**context}}}


def component(id,kind,**props):return {'id':id,'component':kind,**props}


def messages():
    data={'answer_id':'','answer':'','status':'[AIGenerating]正在处理…','notice':'',
          'document':{'id':'','version':'','title':'','sources':''},
          'ui':{'show_choices':False,'show_images':False,'show_file':False,'show_sources':False,'show_feedback':False},
          'resources':{'file':{'name':'','url':'','mime':'','size':0,'description':''},
                       'images':[{'url':'','visible':False} for _ in range(3)]}}
    nodes=[
        component('root','Column',children=['title','status','answer','resource_choices','images_panel','source_file','sources_panel','notice','feedback'],gap=10),
        component('title','Text',text='工作知识助手',bold=True,maxLine=2),
        component('status','Markdown',content=binding('/status')),
        component('answer','Markdown',content=binding('/answer')),
        component('resource_choices','ButtonGroup',responsive=True,gap=8,visible=binding('/ui/show_choices'),buttons=[
            {'label':'查看图片','variant':'primary','action':event('workrag.resource.request',resource_kind='images')},
            {'label':'获取原文件','variant':'default','action':event('workrag.resource.request',resource_kind='source_file')}]),
        component('images_panel','CollapsiblePanel',title='相关图片（点击展开）',
                  children=['image_0','image_1','image_2'],defaultExpanded=False,maxHeight=360,
                  visible=binding('/ui/show_images')),
        component('source_file','File',fileName=binding('/resources/file/name'),url=binding('/resources/file/url'),
                  mimeType=binding('/resources/file/mime'),size=binding('/resources/file/size'),
                  description=binding('/resources/file/description'),visible=binding('/ui/show_file')),
        component('sources_panel','CollapsiblePanel',title='资料来源与版本',children=['sources'],defaultExpanded=False,
                  maxHeight=240,visible=binding('/ui/show_sources')),
        component('sources','Markdown',content=binding('/document/sources')),
        component('notice','Markdown',content=binding('/notice')),
        component('feedback','ButtonGroup',responsive=True,gap=8,visible=binding('/ui/show_feedback'),buttons=[
            {'label':'有帮助','action':event('workrag.feedback',vote='positive')},
            {'label':'需改进','action':event('workrag.feedback',vote='negative')}]),
    ]
    for i in range(3):
        nodes.append(component('image_'+str(i),'Image',url=binding(f'/resources/images/{i}/url'),
                     fit='contain',variant='largeFeature',previewEnabled=True,
                     visible=binding(f'/resources/images/{i}/visible')))
    return [
        {'version':'v1.0','createSurface':{'surfaceId':SURFACE,'catalogId':CATALOG}},
        {'version':'v1.0','updateDataModel':{'surfaceId':SURFACE,'path':'/','value':data}},
        {'version':'v1.0','updateComponents':{'surfaceId':SURFACE,'components':nodes}},
    ]


def update(path,value):
    return {'version':'v1.0','updateDataModel':{'surfaceId':SURFACE,'path':path,'value':value}}


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    def save(name,data):
        (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    card=messages();save('workrag-card.a2ui.json',card)
    save('create-wire.json',{'protocolVersion':'1.0','flowStatus':'PROCESSING',
                           'a2uiMessages':[json.dumps(m,ensure_ascii=False) for m in card]})
    save('stream-update.a2ui.json',[update('/status','正在生成回答…'),update('/answer','[AIGenerating]这是生成中的累计正文。')])
    save('finish-update.a2ui.json',[update('/status','回答完成'),update('/answer','这是完整正文。'),
         update('/ui/show_feedback',True)])
    save('failure-update.a2ui.json',[update('/status','处理未完成'),update('/answer','已取得的有效内容应由服务端填在此处。'),
         update('/notice','本次请求未完成，请稍后重试。'),update('/ui/show_choices',False),update('/ui/show_feedback',False)])
    save('image-update.a2ui.json',[
        update('/resources/images',[{'url':'https://your-authorized-resource-host.example/image-1.png','visible':True},
                                    {'url':'','visible':False},{'url':'','visible':False}]),
        update('/ui/show_images',True)])
    save('file-update.a2ui.json',[
        update('/resources/file',{'name':'企业资料.docx','url':'https://your-authorized-resource-host.example/manual.docx',
                                  'mime':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                                  'size':1024,'description':'当前授权的已发布版本原件'}),update('/ui/show_file',True)])
    save('status.json',{'format':'DingTalk A2UI v1.0','catalog':CATALOG,'legacy_editorData':False,
        'official_lint_verified':False,'cloud_published':False,'active_bot_binding_changed':False,
        'actual_dingtalk_render_verified':False,'callbacks_connected':False,
        'image_panels_default_collapsed':True,'resource_examples_contain_placeholder_urls':True})
    assets=OUT/'assets';assets.mkdir(exist_ok=True)
    fixture=ROOT/'data/manuals/runtime/demo-enterprise'
    for path in fixture.rglob('WRAG-DEMO-EQUIP-01*'):
        if path.is_file() and path.suffix.lower() in {'.png','.docx'}:shutil.copy2(path,assets/path.name)
    preview='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WorkRAG JSON 卡片 V2</title>
<style>*{box-sizing:border-box}body{margin:0;padding:30px 16px;background:#eef2f6;color:#243444;font:15px/1.7 system-ui}main{max-width:740px;margin:auto}.caption{font-size:13px;color:#657789}.card{padding:22px;background:#fff;border:1px solid #dce4ed;border-radius:14px;box-shadow:0 8px 30px #14334d0a}h2{font-size:19px;margin:0 0 8px}button,.download{display:inline-block;padding:8px 14px;border:1px solid #b9cee4;background:white;color:#235e9f;border-radius:20px;cursor:pointer;font:inherit;text-decoration:none;margin:4px 6px 4px 0}.primary{background:#286ac1;color:white;border-color:#286ac1}details{border-top:1px solid #e6edf3;padding:10px 0}summary{cursor:pointer;color:#395e82}details>div{max-height:360px;overflow:auto;padding:10px 0}img{display:block;width:100%;max-width:440px;border-radius:6px;margin:12px auto}#status{color:#657789;font-size:13px}.file{margin:12px 0;padding:12px;background:#f5f8fc;border-radius:8px}.note{color:#8e5a21;font-size:13px}.controls{margin:18px 0}.good{color:#237448}#reply{white-space:pre-wrap;min-height:72px}[hidden]{display:none!important}</style>
<main><p class="caption">本地布局预览 · 非钉钉客户端渲染 · 演示资料，不代表公司制度</p><div class="controls"><button onclick="simulate()">预览生成过程</button><button onclick="reset()">回到初始状态</button></div>
<article class="card"><h2>工作知识助手</h2><div id="status">正在处理…</div><div id="reply"></div><div id="choices" hidden><button class="primary" onclick="showImages()">查看图片</button><button onclick="showFile()">获取原文件</button></div>
<details id="images" hidden><summary>相关图片（点击展开）</summary><div>'''
    for path in sorted(assets.glob('*.png')):
        preview+=f'<img src="assets/{path.name}" alt="明确标记的设备借用演练截图">'
    preview+='''</div></details><div class="file" id="file" hidden>📄 WRAG-DEMO-EQUIP-01.docx <a class="download" href="assets/WRAG-DEMO-EQUIP-01.docx" download>下载演示原文件</a></div>
<details id="sources" hidden><summary>资料来源与版本</summary><div>演示企业｜设备借用演练（虚构测试资料）<br>版本 demo-v1 · WRAG-DEMO-EQUIP-01</div></details><p class="note">按钮回调需服务端接入；此页的点击只演示布局。新协议不能导入旧版 editorData 搭建器。</p><div id="feedback" hidden><button onclick="vote('正反馈')">有帮助</button><button onclick="vote('负反馈')">需改进</button><span id="vote"></span></div></article></main>
<script>let timer;const el=id=>document.getElementById(id);function reset(){clearInterval(timer);el('reply').textContent='';el('status').textContent='正在处理…';for(const id of ['choices','images','file','sources','feedback'])el(id).hidden=true;el('images').open=false;el('sources').open=false;el('vote').textContent=''}function simulate(){reset();el('status').textContent='正在生成回答…';const text='以下为虚构演示资料的操作步骤：\\n1. 填写设备、用途和预计归还日期。\\n2. 核对编号 DEMO-LAPTOP-008，点击“确认借用”。\\n3. 归还时记录“外观正常”，提交归还。\\n\\n需要时，可选择查看图片或获取原文件。';let i=0;timer=setInterval(()=>{el('reply').textContent=text.slice(0,++i);if(i>=text.length){clearInterval(timer);el('status').textContent='回答完成';for(const id of ['choices','sources','feedback'])el(id).hidden=false}},25)}function showImages(){el('images').hidden=false}function showFile(){el('file').hidden=false}function vote(v){el('vote').textContent='本地模拟：'+v}reset()</script></html>'''
    (OUT/'preview.html').write_text(preview,encoding='utf-8')
    print('Built DingTalk A2UI card:',OUT)


if __name__=='__main__':build()
