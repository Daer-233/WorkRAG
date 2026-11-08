"""Local, loss-audited MinerU Markdown preparation. No network or model calls."""
from collections import defaultdict
from hashlib import sha256
import html
import json
from pathlib import Path
import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5


def display_image(path,folder,*,pixel_limit=40_000_000,max_edge=4096):
    """Preserve oversized originals separately; upload a bounded display copy."""
    from PIL import Image, ImageOps
    path=Path(path)
    with Image.open(path) as image:
        if image.width*image.height<=pixel_limit:
            return path,False
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        target=folder/(path.stem+'.display.jpg')
        image=ImageOps.exif_transpose(image)
        image.thumbnail((max_edge,max_edge))
        image.convert('RGB').save(target,format='JPEG',quality=90)
        return target,True

IMAGE = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
CHAPTERS = {'人事篇':'人事篇','行政篇':'行政篇','IT篇':'IT篇','财务篇':'财务篇',
            '公司周边环境':'公司周边环境','ADDRESS':'附录：地址与联系信息'}


def plain(text):
    text=re.sub(r'\\([\\`*_{}\[\]()#+.!|\-])',r'\1',text)
    return re.sub(r'[#*_`]', '',text).strip()


def norm(text):
    return re.sub(r'[\W_]+','',unicodedata.normalize('NFKC',html.unescape(plain(text))).casefold())


def prepare(source,content_list):
    source=Path(source).resolve()
    raw=source.read_text(encoding='utf-8-sig')
    digest=sha256(source.read_bytes()).hexdigest()
    blocks=json.loads(Path(content_list).read_text(encoding='utf-8-sig'))
    pages=defaultdict(list); image_pages=defaultdict(set); native_headings=set()
    for b in blocks:
        page=b.get('page_idx')
        if not isinstance(page,int) or page<0: continue
        if b.get('img_path'): image_pages[Path(b['img_path']).name].add(page+1)
        if b.get('text_level') and isinstance(b.get('text'),str): native_headings.add(norm(b['text']))
        for key in ('text','table_body'):
            if isinstance(b.get(key),str): pages[page+1].append(norm(re.sub(r'<[^>]*>','',b[key])))
    page_text={page:''.join(parts) for page,parts in pages.items()}
    def locate(text):
        # Only exact normalized matches. No nearby-image page propagation.
        paragraphs=[norm(p) for p in re.split(r'\n\s*\n',text)]
        anchors=[p for p in paragraphs if len(p)>=8]
        if not anchors: anchors=[p for p in paragraphs if len(p)>=3]
        matches=[page for page,body in page_text.items() if anchors and all(p in body for p in anchors)]
        return matches[0] if len(matches)==1 else None
    steps=[];groups=[];images={};retained=[];warnings=[]
    group_title='培训概览'; group_start=0; carry=[]; carry_images=[]; qa=False
    def flush():
        nonlocal carry,carry_images,qa
        if carry or carry_images:
            text='\n\n'.join(carry).strip()
            if not text: text=f'{group_title}｜原文配图（未提供图注）'
            page=locate(text) if carry else None
            if not carry and carry_images:
                unique={images[r]['page'] for r in carry_images}
                if len(unique)==1: page=next(iter(unique))
            steps.append({'order':None,'title':plain(carry[0])[:120] if carry else '原文配图',
                'instruction':text,'page':page,'asset_refs':[], 'section_asset_refs':list(dict.fromkeys(carry_images))})
        carry=[];carry_images=[];qa=False
    def close_group():
        nonlocal group_start
        flush()
        if len(steps)>group_start:
            groups.append({'id':str(uuid5(NAMESPACE_URL,digest+':'+group_title+':'+str(group_start))),
                'title':group_title,'start':group_start,'end':len(steps),'confirmed':False})
            group_start=len(steps)
    for raw_paragraph in re.split(r'\n\s*\n',raw):
        raw_paragraph=raw_paragraph.strip()
        if not raw_paragraph: continue
        cleaned=plain(raw_paragraph)
        if re.fullmatch(r'\d+\s*/\s*\d+',cleaned):
            # A printed page boundary is reliable, but must not separate Q/A.
            if not qa or any(re.match(r'^A\s*[:：]',p,re.I) for p in carry): flush()
            continue
        if re.fullmatch(r'LSDCASA再造\s*\|\s*新员工入职培训',cleaned,re.I): continue
        if re.fullmatch(r'\d{1,2}',cleaned): continue
        if not norm(cleaned) and not IMAGE.search(raw_paragraph) and cleaned not in ('→','↓'): continue
        new_group=None
        if cleaned=='公司组织架构': new_group='公司组织架构'
        elif raw_paragraph.startswith('#') and cleaned in CHAPTERS: new_group=CHAPTERS[cleaned]
        if new_group and new_group!=group_title:
            close_group();group_title=new_group
        # Every actual paragraph is retained, including headings and Q/A labels.
        text=IMAGE.sub('',raw_paragraph).strip()
        if text:
            is_q=bool(re.match(r'^Q\s*[:：]',text,re.I))
            is_a=bool(re.match(r'^A\s*[:：]',text,re.I))
            heading=(len(cleaned)<=32 and not re.search(r'[。；！？?\n]',cleaned)
                     and not is_q and not is_a and cleaned not in ('→','↓'))
            has_body=any(len(plain(p))>32 or re.search(r'[。；！？]',p) for p in carry)
            strong_heading=(norm(text) in native_headings or bool(re.match(r'^(?:#{1,6} |\*\*|- \*\*|Top\d+|[①-⑳])',text)))
            if is_q or (qa and not is_a) or (heading and (has_body or (strong_heading and len(carry)>1))): flush()
            elif has_body and len(cleaned)>60 and not is_a and not qa: flush()
            if is_a and not any(re.match(r'^Q\s*[:：]',p,re.I) for p in carry):
                warnings.append('发现未关联问题的回答，需检查')
            carry.append(text);retained.append(text)
            qa=qa or is_q
        for reference in IMAGE.findall(raw_paragraph):
            if re.match(r'^[a-zA-Z]+:|^//',reference): raise ValueError('不自动访问外部图片')
            path=(source.parent/reference).resolve()
            if not path.is_relative_to((source.parent/'images').resolve()) or not path.is_file():
                raise ValueError('图片缺失或超出本地 images 目录')
            candidates=image_pages.get(path.name,set())
            if len(candidates)!=1: raise ValueError('图片原始页码不唯一，需人工检查')
            images[reference]={'path':str(path),'page':next(iter(candidates)),
                'sha256':sha256(path.read_bytes()).hexdigest(),'name':path.name}
            carry_images.append(reference)
    close_group()
    joined='\n\n'.join(s['instruction'] for s in steps)
    if any(re.search(r'^Q\s*[:：]',s['instruction'],re.M) and not re.search(r'^A\s*[:：]',s['instruction'],re.M) for s in steps):
        warnings.append('发现未关联回答的问题，需检查')
    lost=[p for p in retained if p not in joined]
    associated=[r for s in steps for r in s['section_asset_refs']]
    if lost or set(associated)!=set(images): raise ValueError('内容或图片关联审计未通过')
    return {'source_path':str(source),'source_sha256':digest,'content_list_path':str(Path(content_list).resolve()),
        'title':'LSD新员工入职培训','category':'人力行政中心','product':'新员工','version':'',
        'steps':steps,'groups':groups,'images':images,'warnings':list(dict.fromkeys(warnings)),
        'audit':{'retained_text_blocks':len(retained),'lost_text_blocks':len(lost),'images':len(images),
            'all_images_associated':set(associated)==set(images),'children':len(steps),'parents':len(groups),
            'children_with_exact_page':sum(s['page'] is not None for s in steps),
            'source_page_count':max(page_text) if page_text else 0,
            'paired_qa':sum(bool(re.search(r'^Q[:：]',s['instruction'],re.M)) and bool(re.search(r'^A[:：]',s['instruction'],re.M)) for s in steps)}}
