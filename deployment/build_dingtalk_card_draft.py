"""Build a reviewable cloud-import draft; never publish or apply a template."""
import json
import shutil
import sys
from pathlib import Path
from html import escape
from install_agent import ROOT,RUNTIME

sys.path.insert(0,str(ROOT/'scripts'))
from knowledge_card.template import build

out=RUNTIME/'card-draft';out.mkdir(parents=True,exist_ok=True)
payload=build();editor=json.loads(payload['editorData']);folded=[]
def visit(node):
    if isinstance(node,dict):
        if node.get('componentName')=='CollapsePanel' and ('_photos' in node.get('id','') or '_more' in node.get('id','')):
            node['props']['contentVisible']=False;folded.append(node['id'])
        for value in node.values():visit(value)
    elif isinstance(node,list):
        for value in node:visit(value)
visit(editor);assert folded
payload['editorData']=json.dumps(editor,ensure_ascii=False)
(out/'dingtalk-template-collapsed-draft.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
materials=json.loads((RUNTIME/'demo-materials.json').read_text(encoding='utf-8'));sections=[]
assets=out/'assets';assets.mkdir(exist_ok=True)
for doc in materials['documents']:
    file=Path(doc['source_file']);shutil.copy2(file,assets/file.name);images=[]
    for picture in sorted(file.parent.glob(doc['marker']+'-step-*.png')):
        shutil.copy2(picture,assets/picture.name);images.append(f'<figure><img src="assets/{picture.name}" alt="{escape(picture.name)}"><figcaption>{escape(picture.name)}</figcaption></figure>')
    sections.append(f'<article><h2>{escape(doc["title"])}</h2><p>请选择：<button onclick="this.parentNode.parentNode.querySelector(\'details\').hidden=false">图片</button> <a href="assets/{file.name}" download>下载演示原文件</a></p><details hidden><summary>相关图片（默认折叠，点击展开）</summary><div class="images">'+''.join(images)+'</div></details></article>')
html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>钉钉资源卡片本地预览</title><style>body{font:16px/1.7 system-ui;background:#eef2f6;padding:25px;color:#203747}main{max-width:980px;margin:auto}article{background:white;border-radius:14px;padding:24px;margin:20px 0;border-top:4px solid #467ac4}button,a{padding:8px;color:#176c9f}img{width:100%;max-width:340px}.images{display:flex;flex-wrap:wrap}figure{margin:10px;max-width:340px}summary{cursor:pointer}strong{color:#ad3d24}</style><main><h1>图片／文件选择与折叠展示</h1><p><strong>这是本地预览，不是钉钉已发布模板，也不代表媒体已投递。</strong></p><p>用户选择图片后显示折叠区域，点击才展开；选择文件后下载本地演示原件。</p>'''+''.join(sections)+'</main></html>'
(out/'preview.html').write_text(html,encoding='utf-8')
(out/'draft-status.json').write_text(json.dumps({'cloud_published':False,'active_template_changed':False,'image_panels_default_collapsed':True,'choice_in_current_runner':'回复 图片 或 文件；原生按钮待接线','media_delivery_verified':False,'folded_panels':folded},ensure_ascii=False,indent=2),encoding='utf-8')
print('Prepared local preview and cloud-import draft:',out)
