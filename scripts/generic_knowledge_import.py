"""Local text/Markdown import with atomic tables and semantic procedure boundaries."""
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
import json
import re
from uuid import NAMESPACE_URL, uuid5

from mineru_markdown_import import IMAGE, norm, plain

TABLE=re.compile(r'<table\b[^>]*>[\s\S]*?</table>',re.I)
STEP=re.compile(r'^\s*(?:#{1,6}\s*)?(?:\d+[.、．](?!\d)\s*|第\s*\d+\s*步)')
MAJOR=re.compile(r'^\s*(?:#{1,6}\s*)?[一二三四五六七八九十]+[、．]\s*')


def read_text(path):
    raw=Path(path).read_bytes()
    candidates=('utf-16','utf-8-sig','gb18030') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else ('utf-8-sig','gb18030')
    for encoding in candidates:
        try:return raw.decode(encoding).replace('\r\n','\n').replace('\r','\n'),encoding
        except UnicodeError:pass
    raise ValueError('无法可靠识别文本编码')


def comparable(text):
    return norm(re.sub(r'<[^>]*>',' ',text))


def prepare_generic(source,content_list=None,*,title,category='人力行政中心',product='',version=''):
    source=Path(source).resolve();raw,encoding=read_text(source)
    blocks=json.loads(Path(content_list).read_text(encoding='utf-8-sig')) if content_list else []
    digest=sha256(source.read_bytes()).hexdigest()
    page_text=defaultdict(list);image_pages=defaultdict(set);table_images=defaultdict(list)
    for b in blocks:
        index=b.get('page_idx')
        if not isinstance(index,int) or index<0:continue
        page=index+1
        for field in ('text','table_body'):
            if isinstance(b.get(field),str):page_text[page].append(comparable(b[field]))
        if b.get('img_path'):
            image_pages[Path(b['img_path']).name].add(page)
            if b.get('type')=='table' and b.get('table_body'):
                table_images[comparable(b['table_body'])].append(b['img_path'])
    pages={p:''.join(s) for p,s in page_text.items()}
    def locate(text):
        anchors=[comparable(p) for p in text.split('\n') if len(comparable(p))>=8]
        if not anchors:anchors=[comparable(p) for p in text.split('\n') if len(comparable(p))>=2]
        found=[p for p,t in pages.items() if anchors and all(a in t for a in anchors)]
        return found[0] if len(found)==1 else None
    images={};steps=[];groups=[];retained=[];carry=[];picture_refs=[];group_title=title;start=0
    def add_image(reference):
        if re.match(r'^[a-zA-Z]+:|^//',reference):raise ValueError('不读取外部配图')
        path=(source.parent/reference).resolve()
        if not path.is_relative_to((source.parent/'images').resolve()) or not path.is_file():raise ValueError('配图缺失或超出 images 目录')
        mapped=image_pages.get(path.name,set())
        if len(mapped)!=1:raise ValueError('配图页码无法唯一核实')
        images[reference]={'path':str(path),'name':path.name,'page':next(iter(mapped)),
            'sha256':sha256(path.read_bytes()).hexdigest()}
        picture_refs.append(reference)
    def flush():
        nonlocal carry,picture_refs
        if carry or picture_refs:
            instruction='\n\n'.join(carry).strip() or group_title+'｜原文配图（未提供图注）'
            steps.append({'order':None,'title':plain(carry[0])[:120] if carry else '原文配图',
                'instruction':instruction,'page':locate(instruction),'asset_refs':[],
                'section_asset_refs':list(dict.fromkeys(picture_refs))})
        carry=[];picture_refs=[]
    def close():
        nonlocal start
        flush()
        if len(steps)>start:
            groups.append({'id':str(uuid5(NAMESPACE_URL,digest+':'+group_title+':'+str(start))),
                'title':group_title[:300],'start':start,'end':len(steps),'confirmed':False})
            start=len(steps)
    # Preserve whole HTML tables, even if the source contains blank lines inside.
    tokens=[];cursor=0
    for match in TABLE.finditer(raw):
        tokens.extend(raw[cursor:match.start()].splitlines());tokens.append(match[0]);cursor=match.end()
    tokens.extend(raw[cursor:].splitlines())
    for line in tokens:
        stripped=line.strip()
        if not stripped:continue
        if re.fullmatch(r'\d+\s*/\s*\d+',stripped):continue
        bullet=stripped.startswith(('\uf06c','●','•'))
        wifi=bool(re.fullmatch(r'公司\s*WIFI\s*[:：]?',stripped,re.I))
        heading=bool(MAJOR.match(stripped)) or bullet or wifi
        if heading:
            close()
            label=plain(stripped.lstrip('\uf06c●• '))
            group_title=re.split(r'[:：。]',label,maxsplit=1)[0][:100] or title
        elif STEP.match(stripped) or re.match(r'^Q\s*[:：]',stripped,re.I):
            flush()
        elif stripped.lower().startswith('<table'):
            flush()
        text=IMAGE.sub('',stripped).strip()
        if text:
            carry.append(text);retained.append(text)
        for reference in IMAGE.findall(stripped):add_image(reference)
        if stripped.lower().startswith('<table'):
            # Attach only crops with exactly the same table text, not all sibling images.
            for reference in table_images.get(comparable(stripped),[]):add_image(reference)
            flush()
    close()
    full='\n\n'.join(s['instruction'] for s in steps)
    lost=[t for t in retained if t not in full]
    associated={r for s in steps for r in s['section_asset_refs']}
    if lost or associated!=set(images) or not steps:raise ValueError('正文或配图完整性校验失败')
    if any(len(s['instruction'])>20000 for s in steps):raise ValueError('单条流程超过接口限制，需要人工分段')
    if any(len(s['section_asset_refs'])>20 for s in steps):raise ValueError('单条说明配图过多，需要人工检查')
    return {'source_path':str(source),'source_sha256':digest,'content_list_path':str(Path(content_list).resolve()) if content_list else None,
        'title':title,'category':category,'product':product,'version':version,'steps':steps,'groups':groups,
        'images':images,'warnings':[],'encoding':encoding,'audit':{'retained_text_blocks':len(retained),'lost_text_blocks':len(lost),
        'children':len(steps),'parents':len(groups),'images':len(images),'all_images_associated':associated==set(images),
        'children_with_exact_page':sum(s['page'] is not None for s in steps),'source_page_count':max(pages) if pages else None,
        'tables':len(TABLE.findall(raw))}}
