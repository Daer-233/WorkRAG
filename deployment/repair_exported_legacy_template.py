"""Repair only incompatible streaming bindings in the user's actual export."""
import argparse
import copy
import json
from pathlib import Path
from install_agent import RUNTIME

def repair(source):
    original=json.loads(Path(source).read_text(encoding='utf-8-sig'));payload=copy.deepcopy(original)
    editor=json.loads(payload['editorData']);changes=[];panels=[]
    def visit(value):
        if isinstance(value,dict):
            if value.get('componentName')=='MarkdownBlock' and value.get('id'):
                props=value.get('props',{})
                if props.get('content',{}).get('variable')=='answer' and props.get('isStreaming') is True:
                    changes.append({'id':value['id'],'field':'props.isStreaming','before':True,'after':False})
                    props['isStreaming']=False
            if value.get('componentName')=='CollapsePanel' and '_workrag_photos' in value.get('id',''):
                assert value['props']['contentVisible'] is False
                panels.append({'id':value['id'],'images':len(value.get('children',[]))})
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(editor['schema']['componentsTree']);assert changes and panels
    payload['editorData']=json.dumps(editor,ensure_ascii=False)
    out=RUNTIME/'legacy-media-template';out.mkdir(exist_ok=True)
    target=out/'AI工作助手_修复正文与折叠图片.json'
    target.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'source_sha256':__import__('hashlib').sha256(Path(source).read_bytes()).hexdigest(),
            'changes':changes,'unchanged_collapsed_image_panels':panels,'cloud_updated':False,'client_verified':False}
    (out/'export-repair-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Repaired',len(changes),'answer bindings; preserved',len(panels),'collapsed image panels')
    return target

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('source');repair(parser.parse_args().source)
