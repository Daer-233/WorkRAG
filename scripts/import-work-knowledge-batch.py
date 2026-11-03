"""Import the five explicitly supplied files. Defaults to prepare-only mode."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from generic_knowledge_import import prepare_generic

ROOT=Path(__file__).resolve().parents[1]
SPECS=[
    {'source':r'H:\MinerU\费用报销规范.jpg-f1e143a6-3abf-4329-b3ef-018bf011b6e8\MinerU_markdown_202610301703827_0dd5f8e6.md',
     'title':'费用报销规范（交通与住宿标准）','product':'差旅及报销','version':''},
    {'source':r'H:\杂物\IT篇教程.txt','title':'IT篇教程','product':'IT支持','version':''},
    {'source':r'H:\杂物\office安装教学.txt','title':'Office安装教学（原文）','product':'Office','version':''},
    {'source':r'H:\杂物\打印机地址.txt','title':'打印机地址','product':'打印机','version':''},
    {'source':r'H:\MinerU\LSD入职指引（IT）_2025(1)(2)(2).pdf-3dfa95f1-73e0-426a-9216-b3c5d8219252\MinerU_markdown_202610301710209_c0d627e7.md',
     'title':'LSD入职指引（IT）','product':'新员工IT入职','version':'2025（文件名标注）'},
]


def prepared():
    for spec in SPECS:
        source=Path(spec['source']);content=list(source.parent.glob('*_content_list.json')) if source.suffix=='.md' else []
        assert len(content)<=1,'MinerU content list ambiguous'
        yield spec,prepare_generic(source,content[0] if content else None,
            title=spec['title'],product=spec['product'],version=spec['version'])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--import-draft',action='store_true')
    parser.add_argument('--publish-reviewed',action='store_true')
    args=parser.parse_args()
    for spec,plan in prepared():
        command=[sys.executable,str(ROOT/'scripts/import-mineru-markdown.py'),'--generic','--source',spec['source'],
            '--title',spec['title'],'--product',spec['product'],'--version',spec['version']]
        if args.publish_reviewed:command+=['--publish','--confirm-reviewed']
        elif args.import_draft:command+=['--import-draft']
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
        if result.returncode:
            print(result.stderr[-1800:],file=sys.stderr);raise SystemExit(result.returncode)
        for line in result.stdout.splitlines():
            if line.startswith('{'):print(line,flush=True)


if __name__=='__main__':main()
