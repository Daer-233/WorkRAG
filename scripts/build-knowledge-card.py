"""Build template, interactive preview and documented event fixtures locally."""
import argparse
import base64
from io import BytesIO
import json
from pathlib import Path

from knowledge_card.model import CardState, wire_params
from knowledge_card.template import build

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/knowledge-card-v1'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--with-library',action='store_true',help='Use local read-only retrieval and photos')
    args = parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    assets = OUT / 'assets'
    assets.mkdir(exist_ok=True)
    state = CardState()
    if args.with_library:
        import httpx
        from PIL import Image
        with httpx.Client(base_url='http://127.0.0.1:8060',timeout=180,headers={'X-Manual-Request':'1'}) as client:
            response = client.post('/api/v1/manuals/retrieve',json={'query':'请展示 AI 赋能设计培训现场照片','top_k':5,
                'filters':{'entry_id':'1fd0f00d-962d-46a4-b8ff-75701e1db875'}})
            response.raise_for_status()
            state.ingest(response.json())
            assert state.sources and state.images, 'Photo evidence unavailable; no placeholder success output'
            for index,image in enumerate(state.images):
                response = client.get(image['preview_url'])
                response.raise_for_status()
                im = Image.open(BytesIO(response.content)).convert('RGB')
                im.thumbnail((1600,1200))
                full = assets / f'photo-{index+1:02}.jpg'
                im.save(full,quality=86)
                im.thumbnail((288,192))
                thumb = assets / f'thumb-{index+1:02}.jpg'
                im.save(thumb,quality=85)
                image['preview_src'] = f'assets/{full.name}'
                image['src'] = f'assets/{thumb.name}'
                image['media_id'] = '@REPLACE_WITH_UPLOADED_MEDIA_ID'
        state.answer = f'已找到 {len(state.images)} 张 AI 赋能设计培训现场照片，按原资料分类展示。照片与具体课程步骤的对应关系尚未确认。[1]'
    else:
        state.answer = '这里显示基于知识库证据整理的回答。请使用 --with-library 生成真实照片与依据预览。'
    state.apply({'type':'run.completed'})
    params = state.params()
    fixture = {'answer':params['answer'],'sources':params['sources'],
        'images':[{k:i.get(k) for k in ('name','association','src','preview_src','source_number')} for i in state.images]}
    preview = Path(__file__).with_name('knowledge_card').joinpath('preview.html').read_text(encoding='utf-8')
    (OUT/'preview.html').write_text(preview.replace('__PAYLOAD__',json.dumps(fixture,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    (OUT/'dingtalk-template.json').write_text(json.dumps(build(),ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'variables.example.json').write_text(json.dumps(wire_params(params),ensure_ascii=False,indent=2),encoding='utf-8')
    events = [{'type':'run.started'},{'type':'retrieval.started'},
        {'type':'retrieval.completed','results':'Host-authorized retrieval packets, not model-written sources'},
        {'type':'answer.delta','text':'已找到 '},{'type':'answer.delta','text':'相关资料。[1]'},
        {'type':'images.started'},{'type':'image.ready','asset_id':'from_retrieval','media_id':'@uploaded'},
        {'type':'run.completed'}]
    (OUT/'events.example.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'README.md').write_text((ROOT/'docs/knowledge-card-v1-handoff.md').read_text(encoding='utf-8'),encoding='utf-8')
    print(json.dumps({'output':str(OUT),'images':len(state.images),'sources':len(state.sources),
        'cloud_template_validated':False,'active_template_changed':False},ensure_ascii=False))


if __name__ == '__main__': main()
