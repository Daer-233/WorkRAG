"""Pure projection: only retrieved packets can become citations and images."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

UUID = r'[0-9a-fA-F-]{36}'
IMAGE = re.compile(r'!\[[^\]]*\]\([^)]*\)')
LABELS = {'processing':'正在处理','retrieving':'正在检索资料','generating':'正在生成回答',
          'images':'正在准备图片','completed':'回答完成','busy':'知识库正忙，请稍后重试',
          'empty':'未找到可引用的资料','failed':'处理失败，已保留可用内容'}


LABELS.update({'payment_reading':'正在读取表格','payment_preparing':'正在生成预览','payment_review':'需要补充信息','payment_ready':'待平台确认'})


def packets(value, depth=0):
    """Decode only Host tool-result envelopes; callers must not pass model text."""
    if depth > 12:
        return []
    if isinstance(value, str):
        try:
            return packets(json.loads(value), depth + 1)
        except (ValueError, TypeError):
            return []
    if isinstance(value, list):
        return [p for item in value[:100] for p in packets(item, depth + 1)]
    if isinstance(value, dict):
        meta = value.get('metadata', {})
        if not isinstance(meta,dict): return []
        meta = meta.get('knowledge', meta)
        if not isinstance(meta,dict): return []
        if meta.get('result_type') in ('source_evidence','retrieval_notice'):
            return [dict(value, metadata=meta)]
        return [p for key in ('structuredContent','content','results','result','data','text')
                if key in value for p in packets(value[key], depth + 1)]
    return []


@dataclass
class CardState:
    business: bool = False
    stage: str = 'processing'
    answer: str = ''
    sources: list = field(default_factory=list)
    images: list = field(default_factory=list)
    notices: list = field(default_factory=list)
    _packet_ids: set = field(default_factory=set)

    def ingest(self, results):
        incoming = packets(results)
        for packet in incoming:
            meta = packet['metadata']
            if meta.get('result_type') == 'retrieval_notice':
                self.stage = 'busy' if packet.get('id') == 'retrieval_busy' else 'empty'
                continue
            packet_id = packet.get('id')
            if packet_id in self._packet_ids:
                continue
            self._packet_ids.add(packet_id)
            key = (meta.get('entry_id'), meta.get('version'), meta.get('group_id'))
            source = next((s for s in self.sources if s['key'] == key), None)
            if source is None:
                source = {'key': key, 'number':len(self.sources)+1, 'title':meta.get('title') or '资料',
                    'chapter':meta.get('group_title') or '', 'version':meta.get('version'),
                    'pages':[], 'excerpts':[], 'evidence_ids':[], 'file_names':[]}
                self.sources.append(source)
            steps = meta.get('steps', [])
            for step in steps:
                original = step.get('source') or {}
                # Never use retrieval_page as an original document page.
                page = original.get('page')
                if page is not None and page not in source['pages']:
                    source['pages'].append(page)
                file_name = original.get('file_name')
                if file_name and file_name not in source['file_names']:
                    source['file_names'].append(file_name)
                if step.get('is_match', True) and step.get('instruction') not in source['excerpts']:
                    if step.get('instruction'):
                        source['excerpts'].append(step['instruction'])
                source['evidence_ids'] = list(dict.fromkeys(source['evidence_ids'] + step.get('evidence_ids', [])))
            for image in meta.get('images', []):
                if not image.get('asset_id') or any(i['asset_id'] == image['asset_id'] for i in self.images):
                    continue
                if len(self.images) >= 12:
                    if '还有图片未展示，请继续查询。' not in self.notices:
                        self.notices.append('还有图片未展示，请继续查询。')
                    continue
                self.images.append({**image, 'source_number':source['number'], 'media_id':None})
        if any(p['metadata'].get('result_type') == 'source_evidence' for p in incoming):
            self.stage = 'generating'

    def apply(self, event):
        kind = event['type']
        if kind == 'business.updated': self.business = True
        elif kind == 'payment.stage': self.stage = event['stage']
        elif kind == 'retrieval.started': self.stage = 'retrieving'
        elif kind == 'generation.started' and self.stage not in ('busy','empty','failed','payment_review','payment_ready'): self.stage = 'generating'
        elif kind == 'retrieval.completed': self.ingest(event.get('results', []))
        elif kind == 'answer.delta':
            self.answer += event.get('text', '')
            if self.stage not in ('busy','empty','failed','payment_review','payment_ready'): self.stage = 'generating'
        elif kind == 'answer.snapshot':
            self.answer = event.get('text', '')
            if self.answer and self.stage not in ('busy','empty','failed','payment_review','payment_ready'): self.stage = 'generating'
        elif kind == 'images.started': self.stage = 'images'
        elif kind == 'image.ready':
            for image in self.images:
                if image['asset_id'] == event.get('asset_id'): image['media_id'] = event['media_id']
        elif kind == 'image.failed':
            if '部分图片暂时无法加载，文字与依据仍可查看。' not in self.notices:
                self.notices.append('部分图片暂时无法加载，文字与依据仍可查看。')
        elif kind == 'run.failed': self.stage = 'failed'
        elif kind == 'run.completed' and self.stage not in ('busy','empty','failed','payment_review','payment_ready'): self.stage = 'completed'

    def public_answer(self):
        answer = IMAGE.sub('', self.answer)
        for source in self.sources:
            for eid in source['evidence_ids']:
                answer = answer.replace(f'[[cite:{eid}]]', f"[{source['number']}]")
                answer = answer.replace(f'`{eid}`', f"[{source['number']}]")
        answer = re.sub(r'\[\[cite:[^\]]+\]\]', '', answer)
        answer = re.sub(r'\[(\d+)\]', lambda m: m[0] if 1 <= int(m[1]) <= len(self.sources) else '', answer)
        answer = re.sub(r'[（(]?\s*证据\s*ID\s*[:：]?\s*`?' + UUID + r'`?\s*[）)]?', '', answer)
        answer = re.sub(r'https?://(?:127\.0\.0\.1|localhost):8060\S*', '', answer)
        return re.sub(r'\n\s*\n\s*\n', '\n\n', answer).strip()

    def params(self):
        data = {'flowStatus':'5' if self.stage == 'failed' else '3' if self.stage in ('completed','busy','empty') else '2',
                'status':LABELS[self.stage], 'answer':self.public_answer(), 'notice':'\n'.join(self.notices),
                'hasImages':'true' if self.images else '', 'hasMoreImages':'true' if len(self.images)>3 else '',
                'hasSources':'true' if self.sources else '', 'imagesTitle':f'相关图片 · {len(self.images)} 张',
                'moreImagesTitle':f'查看全部 {len(self.images)} 张',
                'imagesNote':'章节配图未确认与具体步骤的对应关系。' if any(i.get('association') != 'step' for i in self.images) else '步骤配图，依据见对应来源。',
                'images':[], 'sources':[]}
        for n in range(12):
            image = self.images[n] if n < len(self.images) else None
            data.update({f'image_{n}':image.get('media_id') or '' if image else '',
                f'image_visible_{n}':'true' if image and image.get('media_id') else '',
                f'image_name_{n}':image.get('name') or '相关图片' if image else ''})
            if image:
                data['images'].append({k:image.get(k) for k in ('asset_id','name','association','source_number','media_id')})
            source = self.sources[n] if n < len(self.sources) else None
            location = ''
            if source:
                location = ' · '.join(filter(None,[source['chapter'],
                    f"版本 {source['version']}" if source['version'] else '版本未标注',
                    '第 '+ '、'.join(map(str,source['pages']))+' 页' if source['pages'] else '原资料未提供页码']))
                data['sources'].append({k:source[k] for k in ('number','title','chapter','version','pages','excerpts','file_names')})
            data.update({f'source_visible_{n}':'true' if source else '',
                f'source_title_{n}':f"[{source['number']}] {source['title']}" if source else '',
                f'source_location_{n}':location,
                f'source_excerpt_{n}':'\n\n'.join(source['excerpts']) if source else ''})
        if len(self.sources) > 12:
            data['notice'] += '\n还有依据未在卡片中展开，请继续查询。'
        return data


def wire_params(params):
    """Card API accepts string values even for object/array variables."""
    return {k: json.dumps(v, ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in params.items()}
