"""Independent scope/action BM25, with abstention guards, never score boosts."""
from dataclasses import dataclass
from functools import lru_cache
import math
import re

from .bm25 import BM25,ranking,tokenize
from .settings import ROOT,read_json
from .types import Axes

POLICY=ROOT/'instances/manuals/intent-policy.v2.json'


@lru_cache(maxsize=4)
def _policy(stamp):return read_json(POLICY)


def policy():return _policy(POLICY.stat().st_mtime_ns)


def contains(text,items):return any(value.casefold() in text.casefold() for value in items)


@dataclass
class Signals:
    instruction:str
    clauses:list[str]
    transform:bool
    provided_text:bool
    company:bool
    company_strong:bool
    visual:bool
    file:bool
    reasons:list[str]
    clarification:str=''


def inspect_request(request):
    cfg=policy();text=request.text.strip();instruction=text;payload=''
    transform=contains(text,cfg['transform_markers'])
    directive=bool(re.match(r'^(?:请帮我|帮我|麻烦|能否|可以|请你|替我|帮忙|我要|我想|请){0,3}(?:润色|改写|翻译|缩短|精简|改礼貌|校对|总结这|概括这|把|将)',text))
    directive=directive or (contains(text,cfg['lookup_markers']) and bool(re.match(r'^(?:请|帮我|根据|按|先查|查询|对照|核实)',text)))
    if not directive:transform=False
    # Asking how to edit is distinct from requesting a transformation now.
    if re.match(r'^(?:请问)?(?:如何|怎么|怎样|为什么|什么是)',text):transform=False
    if transform:
        if re.search(r'[:：\n]',text):instruction,payload=re.split(r'[:：\n]',text,maxsplit=1)
        else:
            quote=re.search(r'[“「](.+?)[”」]',text,re.S)
            if quote:payload=quote[1];instruction=text[:quote.start()]+'待处理文字'+text[quote.end():]
    if transform and not payload and re.search(r'怎么|怎样|如何|原理|方法|技巧',instruction):transform=False
    provided=transform and bool(re.search(r'[\w\u4e00-\u9fff]',payload))
    external=contains(instruction,cfg['lookup_markers'])
    company=contains(instruction,cfg['company_markers']+cfg['business_markers'])
    strong=contains(instruction,cfg['company_markers']) and not contains(instruction,cfg['general_markers'])
    if provided and not external:company=False;strong=False
    visual=contains(instruction,cfg['visual_markers']) and contains(instruction,cfg['visual_requests'])
    file=contains(instruction,cfg['file_markers']) and contains(instruction,cfg['file_requests'])
    clauses=[x.strip() for x in re.split(r'[，,。！？!?；;\n]|(?=然后|再查|再问|再帮我|顺便|另外|同时)',instruction) if len(x.strip())>=2]
    reasons=[];clarification=''
    if transform and not provided:
        clarification='missing_transform_text';reasons.append(clarification)
    normalized=text.rstrip('。！？!?,， ')
    reference=normalized in cfg['reference_only'] or bool(re.fullmatch(r'(?:这个|那个|上面那个|它|这些|这两个)(?:呢|怎么弄|怎么办|怎么处理|有什么区别|发一下|发我)?',normalized))
    if reference:
        reasons.append('requires_conversation_context')
        if not any(t.text.strip() for t in request.history):clarification=clarification or 'missing_reference_context'
    if not provided and re.search(r'这份|那份|那句话|刚才|上面|前面|右边|第一张|第二个|第三段|背面|上传|(?:根据|对照|依据|处理)附件|附件(?:里|中|给出的)|扫描件|录音',instruction):
        # These expressions can be meaningful with context. Do not guess or
        # grant a direct route solely from an otherwise matching topic.
        reasons.append('requires_conversation_context')
    if visual and file:reasons.append('multiple_output_requests')
    if re.search(r'不(?:要|用|是)|别(?:给|发|查|展示)|而是|只要',instruction):reasons.append('negated_or_contrastive_request')
    if 'image' in request.attachment_types:reasons.append('employee_image_not_read')
    if len(text)>600:reasons.append('long_or_compound_message')
    return Signals(instruction,clauses,transform,provided,company,strong,visual,file,reasons,clarification)


class AxisIndex:
    def __init__(self,rows,field,text_field,stopwords=()):
        self.rows=rows;self.field=field;self.stopwords=set(stopwords);self.action=text_field=='action_text'
        projected=[{'text':' '.join(t for t in tokenize(r[text_field]) if t not in self.stopwords),'intent':r[field]} for r in rows]
        # The prepared tokens are ASCII-separated; avoid re-tokenizing Chinese
        # bigrams into cross-boundary pairs by retaining the original counters.
        self.model=BM25(projected)
        from collections import Counter
        self.model.terms=[Counter(t for t in tokenize(r[text_field]) if t not in self.stopwords) for r in rows]
        self.model.lengths=[sum(t.values()) for t in self.model.terms]
        self.model.average=sum(self.model.lengths)/max(1,len(rows)) or 1
        frequency=Counter(t for terms in self.model.terms for t in terms)
        self.model.idf={t:math.log1p((len(rows)-n+.5)/(n+.5)) for t,n in frequency.items()}

    def evidence(self,text):
        query=set(tokenize(text))-self.stopwords;model=self.model;by_label={}
        for row,terms,length in zip(self.rows,model.terms,model.lengths):
            score=sum(model.idf[t]*(terms[t]*(model.k1+1))/(terms[t]+model.k1*(1-model.b+model.b*length/model.average)) for t in query if terms.get(t))
            by_label.setdefault(row[self.field],[]).append((score,row['family'],terms))
        values={};details={}
        for label,items in by_label.items():
            unique=[];families=set()
            for item in sorted(items,key=lambda x:-x[0]):
                if item[1] not in families:unique.append(item);families.add(item[1])
                if len(unique)==2:break
            first=unique[0];second=unique[1][0] if len(unique)>1 else 0
            score=(first[0]+second)/2
            unknown=max(model.idf.values(),default=1)
            # Company/action coverage concerns the classifier vocabulary, not
            # every unseen document subject. General answers additionally keep
            # unknown terms, so a familiar greeting cannot cover a new business
            # request. Neither projection changes the raw BM25 match score.
            coverage_query=query.intersection(model.idf) if self.action or label=='company' else query
            total=sum(model.idf.get(t,unknown) for t in coverage_query)
            matched=sum(model.idf.get(t,unknown) for t in coverage_query if t in first[2])
            coverage=matched/total if total else 0
            values[label]=score;details[label]={'score':score,'coverage':coverage,'support':second/max(first[0],1e-9)}
        label,score,gap=ranking(values)
        return {'label':label,'scores':values,'score':score,'margin':gap/max(score,1e-9),**{k:v for k,v in details[label].items() if k!='score'}}


def passes(evidence,gates):
    gate=gates.get(evidence['label'])
    return bool(gate and evidence['score']>0 and all(evidence[key]>=gate[key] for key in ('score','margin','coverage','support')))


class FactorBM25:
    def __init__(self,rows):
        self.scope=AxisIndex(rows,'knowledge_scope','text')
        self.output=AxisIndex(rows,'output_kind','action_text',policy()['action_stopwords'])

    def features(self,request):
        signals=inspect_request(request)
        scope_query=signals.instruction
        if signals.provided_text and not signals.company:
            scope_query='处理已提供文字 '+ ' '.join(v for v in policy()['transform_markers'] if v in signals.instruction)
        scope=self.scope.evidence(scope_query)
        company_clauses=[self.scope.evidence(c) for c in signals.clauses] if signals.company else []
        company_clauses=[c for c in company_clauses if c['label']=='company']
        if company_clauses:scope=max(company_clauses,key=lambda c:c['score'])
        action=self.output.evidence(signals.instruction)
        return {'signals':signals,'scope':scope,'output':action}

    def guard(self,features):
        s=features['signals'];scope=features['scope']['label'];output=features['output']['label'];reasons=list(s.reasons)
        if s.clarification:reasons.append(s.clarification)
        if scope=='general' and s.company:reasons.append('daily_company_evidence_veto')
        if output=='images' and not s.visual:reasons.append('image_request_not_supported_by_action')
        if output=='source_file' and not s.file:reasons.append('file_request_not_supported_by_action')
        if scope=='general' and output!='text':reasons.append('scope_output_disagreement')
        if s.provided_text and not s.company and output!='text':reasons.append('provided_text_is_data')
        if output=='text' and not s.provided_text:
            wants_visual=s.visual or (contains(s.instruction,policy()['visual_markers']) and contains(s.instruction,['我要','我需要']))
            if wants_visual or s.file:reasons.append('explicit_media_request_cannot_be_silently_text')
        return list(dict.fromkeys(reasons))

    def decide(self,request,artifact):
        features=self.features(request);reasons=self.guard(features)
        # Image attachments can coexist with text questions, but ambiguous
        # attachment-related wording must be interpreted by the semantic layer.
        blockers=[r for r in reasons if r!='employee_image_not_read']
        if 'image' in request.attachment_types and features['output']['label']=='images':blockers.append('uploaded_image_is_not_a_retrieval_request')
        if not blockers and passes(features['scope'],artifact.get('scope',{})) and passes(features['output'],artifact.get('output',{})):
            gate=artifact['scope'][features['scope']['label']]
            if features['scope']['label']=='general':
                if features['scope']['coverage']<max(gate['coverage'],policy()['daily_min_coverage']):blockers.append('daily_coverage_too_low')
                elif not features['signals'].provided_text and any(self.scope.evidence(c)['coverage']<gate['coverage'] for c in features['signals'].clauses):blockers.append('daily_clause_not_covered')
            if not blockers:
                return Axes(knowledge_scope=features['scope']['label'],output_kind=features['output']['label'],needs_clarification=False),features,reasons
        if not blockers:blockers.append('below_calibrated_axis_thresholds')
        return None,features,list(dict.fromkeys(reasons+blockers))


def validate_semantic(axes,request):
    signals=inspect_request(request)
    if not axes.needs_clarification and axes.knowledge_scope=='general' and signals.company_strong:
        return Axes(knowledge_scope='company',output_kind='text',needs_clarification=True),'company_scope_conflict'
    return axes,''
