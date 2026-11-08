"""Import an existing local MinerU Markdown result; never calls external parsing.

Default is a local dry run. --import-draft persists a reviewable draft.
--publish --confirm-reviewed confirms a reviewed draft and queues its index.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil

import httpx

from mineru_markdown_import import prepare, display_image
from generic_knowledge_import import prepare_generic

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--content-list',type=Path)
    parser.add_argument('--import-draft',action='store_true')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--confirm-reviewed',action='store_true')
    parser.add_argument('--new-draft-version',action='store_true',help='Preserve the published entry and create a revised draft')
    parser.add_argument('--generic',action='store_true')
    parser.add_argument('--title')
    parser.add_argument('--category',default='人力行政中心')
    parser.add_argument('--product',default='')
    parser.add_argument('--version',default='')
    args=parser.parse_args()
    candidates=list(args.source.parent.glob('*_content_list.json'))
    content=args.content_list or (candidates[0] if len(candidates)==1 else None)
    if args.generic:
        plan=prepare_generic(args.source,content,title=args.title or args.source.stem,
            category=args.category,product=args.product,version=args.version)
    else:
        if content is None: raise SystemExit('请明确指定 MinerU content_list.json')
        plan=prepare(args.source,content)
    runtime=ROOT/'data/manuals/runtime/mineru-imports'/plan['source_sha256']
    runtime.mkdir(parents=True,exist_ok=True)
    plan_path=runtime/'prepared.json'
    plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'status':'prepared','audit':plan['audit'],'warnings':plan['warnings'],
        'groups':[{'title':g['title'],'children':g['end']-g['start']} for g in plan['groups']],
        'review_file':str(plan_path),'active_writes':False}
    if not args.import_draft and not args.publish:
        print(json.dumps(report,ensure_ascii=True));return
    if args.publish and not args.confirm_reviewed:
        raise SystemExit('发布前先检查 prepared.json 和草稿；发布要求 --confirm-reviewed')
    if args.publish and plan['warnings']:
        raise SystemExit('存在未解决的内容边界警告，暂不发布')
    manifest_path=runtime/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'assets':{}}
    def checkpoint(): manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=ROOT/'data/manuals/originals/mineru-imports'/plan['source_sha256']
    originals=[(args.source,archive/args.source.name)]
    if content:originals.append((content,archive/'content_list.json'))
    originals.extend((Path(i['path']),archive/'images'/Path(i['path']).name) for i in plan['images'].values())
    for original,target in originals:
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and sha256(target.read_bytes()).digest()!=sha256(original.read_bytes()).digest():
            raise SystemExit('原始资料归档内容冲突，停止覆盖')
        if not target.exists(): shutil.copy2(original,target)
    manifest['original_archive']=str(archive);checkpoint()
    with httpx.Client(base_url='http://127.0.0.1:8060',headers={'X-Manual-Request':'1'},timeout=180) as client:
        def call(method,path,**kwargs):
            response=client.request(method,path,**kwargs)
            response.raise_for_status()
            return response.json()
        prefix='/api/v1/manuals'
        if args.new_draft_version and manifest.get('entry_id'):
            previous=call('GET',prefix+'/entries/'+manifest['entry_id'])
            if previous['status']=='published':
                (runtime/('history-'+manifest['entry_id']+'.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
                manifest={'assets':{},'previous_entry_id':previous['id'],'original_archive':str(archive)}
                checkpoint()
        if not manifest.get('entry_id'):
            existing=call('GET',prefix+'/entries')
            if any(e['title']==plan['title'] and e['id']!=manifest.get('previous_entry_id') and e['status']!='superseded' for e in existing):
                raise SystemExit('已有同名资料但缺少本次导入清单，停止以免重复创建或覆盖')
            categories=call('GET',prefix+'/categories')
            category=next((c for c in categories if c['name']==plan['category']),None)
            if category is None: category=call('POST',prefix+'/categories',json={'name':plan['category']})
            entry=call('POST',prefix+'/entries',json={'title':plan['title'],'category_id':category['id'],
                       'product':plan['product'],'version':plan['version']})
            manifest.update(entry_id=entry['id'],source_sha256=plan['source_sha256']);checkpoint()
        eid=manifest['entry_id']
        entry=call('GET',prefix+'/entries/'+eid)
        if entry['status']=='published':
            print(json.dumps({'status':'already_published','entry_id':eid,'index_status':entry['index_status']},ensure_ascii=True));return
        assert entry['status']=='draft' and entry['title']==plan['title']
        if not entry.get('source_name'):
            with args.source.open('rb') as file:
                call('POST',prefix+f'/entries/{eid}/files',files={'file':(args.source.name,file,'text/markdown')})
        else:
            source=client.get(entry['source_url']);source.raise_for_status()
            if sha256(source.content).hexdigest()!=plan['source_sha256']:
                raise SystemExit('已归档原文与当前 Markdown 不一致，停止覆盖')
        for reference,image in plan['images'].items():
            if reference in manifest['assets'] and manifest['assets'][reference]['sha256']!=image['sha256']:
                raise SystemExit('同一路径图片内容已变化，停止复用旧图片；应创建新版导入')
            if reference not in manifest['assets']:
                path=Path(image['path'])
                upload_path,derivative=display_image(path,runtime/'display-images')
                with upload_path.open('rb') as file:
                    asset=call('POST',prefix+f'/entries/{eid}/files',files={'file':(
                        f"p{image['page']:02}_{upload_path.name}",file)},data={'page':str(image['page'])})
                manifest['assets'][reference]={'asset_id':asset['asset_id'],'sha256':image['sha256'],'page':image['page'],
                    'display_derivative':derivative,'original_archive':str(archive/'images'/path.name)};checkpoint()
        steps=[]
        for original in plan['steps']:
            step={k:v for k,v in original.items() if not k.endswith('_refs')}
            step['asset_ids']=[]
            step['section_asset_ids']=[manifest['assets'][r]['asset_id'] for r in original['section_asset_refs']]
            steps.append(step)
        groups=[dict(g,confirmed=bool(args.confirm_reviewed)) for g in plan['groups']]
        entry=call('PUT',prefix+f'/entries/{eid}/steps',json={'steps':steps,'groups':groups})
        # Audit the stored draft, not only the parser's in-memory output.
        stored=call('GET',prefix+'/entries/'+eid)
        assert len(stored['steps'])==len(steps) and len(stored['assets'])==len(plan['images'])
        actual_pages={a['asset_id']:a['page'] for a in stored['assets']}
        assert all(actual_pages.get(a['asset_id'])==a['page'] for a in manifest['assets'].values())
        assert all(a['instruction']==b['instruction'] and a['page']==b['page'] and
                   a['section_asset_ids']==b['section_asset_ids'] for a,b in zip(stored['steps'],steps))
        assert all(a['title']==b['title'] and a['start']==b['start'] and a['end']==b['end'] for a,b in zip(stored['groups'],groups))
        archived=client.get(stored['source_url']);archived.raise_for_status()
        assert sha256(archived.content).hexdigest()==plan['source_sha256']
        if args.publish:
            entry=call('POST',prefix+f'/entries/{eid}/publish')
        manifest.update(status=entry['status'],audit=plan['audit'],confirmed=bool(args.confirm_reviewed));checkpoint()
        print(json.dumps({**report,'status':entry['status'],'entry_id':eid,'index_status':entry['index_status'],
            'stored_assets':len(stored['assets']),'archived_source_verified':True,'active_writes':True},ensure_ascii=True))


if __name__=='__main__': main()
