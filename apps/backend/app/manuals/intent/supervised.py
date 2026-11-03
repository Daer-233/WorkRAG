"""Task-trained BERT factors. No NLI hypotheses or model downloads at runtime."""
import json
import math
from pathlib import Path

from .settings import DATA,digest,read_json
from .types import Axes,RouteRequest

LABEL_MAP={
    'scope':['general','company','unknown'],
    'output':['text','images','source_file','unknown'],
    'clarification':['answer','clarify'],
}
SCHEMA='bert-axes-v3'


def model_text(request):
    """Only caller-supplied text and Host metadata, never training labels."""
    parts=[request.text.strip()]
    if request.attachment_types:parts.append('附件类型：'+','.join(request.attachment_types))
    if request.previous_file_offer or request.previous_sources:
        parts.append(f'上一轮文件提醒：{int(request.previous_file_offer)}；实际来源数量：{len(request.previous_sources)}')
    if request.history:
        parts.append('最近对话：'+'；'.join(t.role+'：'+t.text[-120:] for t in request.history[-4:]))
    return '\n'.join(parts)


def targets(row):
    return [LABEL_MAP['scope'].index(row['knowledge_scope']),LABEL_MAP['output'].index(row['output_kind']),int(row['needs_clarification'])]


def decode(scores):
    values={};certainty=[];margins=[]
    for name,labels in LABEL_MAP.items():
        axis=scores.get(name)
        if not isinstance(axis,dict) or set(axis)!=set(labels):raise ValueError('Invalid supervised label mapping')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in axis.values()):raise ValueError('Invalid classifier scores')
        if abs(sum(axis.values())-1)>.001:raise ValueError('Classifier scores do not sum to one')
        ranked=sorted(labels,key=lambda k:-axis[k]);values[name]=ranked[0]
        certainty.append(axis[ranked[0]]);margins.append(axis[ranked[0]]-axis[ranked[1]])
    try:
        axes=Axes(knowledge_scope=values['scope'],output_kind=values['output'],needs_clarification=values['clarification']=='clarify')
    except ValueError:return None,min(certainty),min(margins)
    return axes,min(certainty),min(margins)


def accept(scores,gates):
    if scores.get('truncated'):return None,'classifier_input_truncated'
    axes,confidence,margin=decode(scores)
    if axes is None:return None,'classifier_factors_inconsistent'
    gate=gates.get(axes.intent)
    if not gate or confidence<gate['confidence'] or margin<gate['margin']:return None,'below_calibrated_classifier_thresholds'
    return axes,''


def guarded_accept(scores,gates,request):
    """Semantic agreement is required; never turn a veto into a correct hit."""
    from .factors import inspect_request,contains,policy
    axes,reason=accept(scores,gates)
    if axes is None:return None,reason
    signals=inspect_request(request)
    if signals.clarification and not axes.needs_clarification:return None,'classifier_missing_information_conflict'
    if axes.knowledge_scope=='general' and not axes.needs_clarification:
        # Generic words such as '一般' cannot erase explicit company scope.
        explicit=contains(signals.instruction,policy()['company_markers'])
        conceptual=signals.instruction.startswith(('什么是公司','什么是企业','解释公司这个词'))
        if ((explicit or signals.company) and not signals.provided_text and not conceptual) or signals.company_strong:
            return None,'classifier_company_scope_conflict'
    if not axes.needs_clarification and not signals.provided_text and 'negated_or_contrastive_request' not in signals.reasons:
        if signals.visual and axes.output_kind!='images':return None,'classifier_explicit_image_request_conflict'
        if signals.file and axes.output_kind!='source_file':return None,'classifier_explicit_file_request_conflict'
    return axes,''


def verify_manifest(folder):
    folder=Path(folder).resolve();root=(DATA/'models/intent').resolve()
    if not folder.is_relative_to(root):raise ValueError('Supervised model outside intent root')
    manifest=read_json(folder/'intent-manifest.json')
    if manifest.get('schema')!=SCHEMA or manifest.get('labels')!=LABEL_MAP:raise ValueError('Missing or mismatched supervised labels')
    if not 16<=manifest.get('max_length',0)<=256:raise ValueError('Invalid classifier input length')
    base=(folder/manifest['base_relative_dir']).resolve()
    if not base.is_relative_to(root):raise ValueError('Base BERT outside intent root')
    if digest(base/'intent-manifest.json')!=manifest['base_manifest_sha256']:raise ValueError('Base BERT manifest mismatch')
    base_manifest=read_json(base/'intent-manifest.json')
    for owner,files in [(base,base_manifest['files']),(folder,manifest['files'])]:
        if not files:raise ValueError('Empty model checksum list')
        for name,expected in files.items():
            path=(owner/name).resolve()
            if not path.is_relative_to(owner) or digest(path)!=expected:raise ValueError('Supervised model checksum mismatch')
    return manifest,base


def build_network(base_path):
    import torch
    from torch import nn
    from transformers import BertModel
    class Network(nn.Module):
        def __init__(self):
            super().__init__()
            self.bert=BertModel.from_pretrained(base_path,local_files_only=True,trust_remote_code=False,attn_implementation='eager')
            hidden=self.bert.config.hidden_size
            self.dropout=nn.Dropout(.1)
            self.heads=nn.ModuleDict({name:nn.Sequential(nn.Linear(hidden,256),nn.Tanh(),nn.Dropout(.1),nn.Linear(256,len(labels))) for name,labels in LABEL_MAP.items()})

        def mask(self,mask):
            return (1-mask[:,None,None,:].to(dtype=next(self.parameters()).dtype))*torch.finfo(next(self.parameters()).dtype).min

        def lower(self,encoded):
            hidden=self.bert.embeddings(input_ids=encoded['input_ids'],token_type_ids=encoded.get('token_type_ids'))
            attention=self.mask(encoded['attention_mask'])
            for layer in self.bert.encoder.layer[:-1]:hidden=layer(hidden,attention_mask=attention)[0]
            return hidden

        def upper(self,hidden,mask):
            hidden=self.bert.encoder.layer[-1](hidden,attention_mask=self.mask(mask))[0]
            pooled=self.dropout(self.bert.pooler(hidden))
            return {name:head(pooled) for name,head in self.heads.items()}

        def forward(self,**encoded):return self.upper(self.lower(encoded),encoded['attention_mask'])

        def tune_last_layer(self):
            for parameter in self.parameters():parameter.requires_grad_(False)
            for module in (self.bert.encoder.layer[-1],self.bert.pooler,self.heads):
                for parameter in module.parameters():parameter.requires_grad_(True)

    return Network()


def load_network(folder):
    from safetensors.torch import load_file
    from transformers import AutoTokenizer
    manifest,base=verify_manifest(folder)
    model=build_network(base)
    state=model.state_dict();delta=load_file(str(Path(folder)/'delta.safetensors'),device='cpu')
    allowed={key for key in state if key.startswith(('bert.encoder.layer.'+str(len(model.bert.encoder.layer)-1)+'.','bert.pooler.','heads.'))}
    if set(delta)!=allowed:raise ValueError('Unexpected trained parameter set')
    state.update(delta);model.load_state_dict(state,strict=True);model.eval()
    tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True,trust_remote_code=False)
    return model,tokenizer,manifest


def infer(model,tokenizer,text,max_length):
    import torch
    encoded=tokenizer(text,truncation=False,return_tensors='pt')
    count=encoded['input_ids'].shape[1]
    if count>max_length:return {'truncated':True,'token_count':count}
    with torch.inference_mode():logits=model(**encoded)
    scores={name:dict(zip(labels,logits[name].softmax(-1)[0].tolist())) for name,labels in LABEL_MAP.items()}
    return {**scores,'truncated':False,'token_count':count}


def worker(pipe,folder):
    try:
        import torch
        torch.set_num_threads(2);torch.set_num_interop_threads(1)
        model,tokenizer,manifest=load_network(folder)
        for _ in range(2):infer(model,tokenizer,'请查询本公司的内部办理流程',manifest['max_length'])
        pipe.send({'ready':True})
        while True:
            payload=pipe.recv()
            if payload is None:break
            request=RouteRequest.model_validate(payload)
            pipe.send({'scores':infer(model,tokenizer,model_text(request),manifest['max_length'])})
    except (EOFError,BrokenPipeError):pass
    except Exception as exc:
        try:pipe.send({'error':type(exc).__name__})
        except (EOFError,BrokenPipeError):pass
    finally:pipe.close()
