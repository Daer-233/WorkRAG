"""Offline supervised BERT top-layer and factor heads training on CPU.

Only train/development are read. Lower 11 frozen encoder layers are cached;
only the final encoder layer, pooler and three task heads are updated.
"""
import argparse
import json
import os
from pathlib import Path
import random
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
from dotenv import load_dotenv
load_dotenv(ROOT/'instances/manuals/.env',override=True)
from app.manuals.intent.settings import DATA,MODEL,digest
from app.manuals.intent.supervised import LABEL_MAP,SCHEMA,build_network,model_text,targets
from app.manuals.intent.types import RouteRequest

def main():
 p=argparse.ArgumentParser();p.add_argument('--epochs',type=int,default=10);args=p.parse_args()
 import torch
 from safetensors.torch import save_file
 from transformers import AutoTokenizer
 torch.manual_seed(7303);random.seed(7303);torch.set_num_threads(4);torch.set_num_interop_threads(1)
 out=DATA/'models/intent/supervised-bert-v3';out.mkdir(parents=True,exist_ok=True)
 if (out/'intent-manifest.json').exists():raise RuntimeError('Trained model already sealed; use a new version for retraining')
 source=ROOT/'instances/manuals/intent-samples/v3'
 sets={name:[json.loads(s) for s in (source/(name+'.jsonl')).read_text(encoding='utf-8').splitlines()] for name in ('train','development')}
 assert not {r['family'] for r in sets['train']} & {r['family'] for r in sets['development']}
 model=build_network(MODEL);model.tune_last_layer();model.eval()
 tokenizer=AutoTokenizer.from_pretrained(MODEL,local_files_only=True,trust_remote_code=False)
 cache={};max_length=96
 for name,rows in sets.items():
  hidden=[];masks=[];ys=[]
  for start in range(0,len(rows),16):
   batch=rows[start:start+16]
   texts=[model_text(RouteRequest.model_validate({k:v for k,v in r.items() if k in RouteRequest.model_fields})) for r in batch]
   encoded=tokenizer(texts,padding='max_length',truncation=True,max_length=max_length,return_tensors='pt')
   with torch.no_grad():hidden.append(model.lower(encoded).detach())
   masks.append(encoded['attention_mask']);ys.extend(targets(r) for r in batch)
   if start%160==0:print(json.dumps({'cache':name,'completed':start,'total':len(rows)}),flush=True)
  cache[name]=(torch.cat(hidden),torch.cat(masks),torch.tensor(ys))
 optimizer=torch.optim.AdamW([
  {'params':list(model.bert.encoder.layer[-1].parameters())+list(model.bert.pooler.parameters()),'lr':2e-5},
  {'params':model.heads.parameters(),'lr':8e-4}],weight_decay=.01)
 best=-1;history=[];best_state=None;stale=0
 for epoch in range(args.epochs):
  started=time.monotonic();model.train();hidden,masks,ys=cache['train'];loss_sum=0
  # Frozen lower-layer dropout never enters cache; only upper training dropout.
  for ids in torch.randperm(len(ys)).split(16):
   optimizer.zero_grad(set_to_none=True);logits=model.upper(hidden[ids],masks[ids])
   loss=sum(torch.nn.functional.cross_entropy(logits[name],ys[ids,j]) for j,name in enumerate(LABEL_MAP))
   loss.backward();torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],1.0);optimizer.step();loss_sum+=loss.item()*len(ids)
  model.eval();hidden,masks,ys=cache['development'];pred=[]
  with torch.no_grad():
   for ids in torch.arange(len(ys)).split(16):
    logits=model.upper(hidden[ids],masks[ids]);pred.append(torch.stack([logits[name].argmax(-1) for name in LABEL_MAP],1))
  predicted=torch.cat(pred);exact=(predicted==ys).all(1).float().mean().item()
  record={'epoch':epoch+1,'loss':loss_sum/len(cache['train'][2]),'development_axes_exact':exact,'seconds':round(time.monotonic()-started,2)};history.append(record);print(json.dumps(record),flush=True)
  if exact>best:
   best=exact;stale=0;best_epoch=epoch+1
   best_state={k:v.detach().clone().contiguous() for k,v in model.state_dict().items() if k.startswith((f'bert.encoder.layer.{len(model.bert.encoder.layer)-1}.','bert.pooler.','heads.'))}
  else:stale+=1
  if stale>=4:break
 save_file(best_state,str(out/'delta.safetensors'))
 manifest={'schema':SCHEMA,'labels':LABEL_MAP,'max_length':max_length,'base_relative_dir':'../erlangshen-110m-nli',
  'base_manifest_sha256':digest(MODEL/'intent-manifest.json'),'files':{'delta.safetensors':digest(out/'delta.safetensors')},
  'seed':7303,'trained_encoder_layers':[11],'frozen_encoder_layers':list(range(11)),
  'selection_data':'development_only','best_epoch':best_epoch,'development_axes_exact':best,
  'data_sha256':{name:digest(source/(name+'.jsonl')) for name in sets},'counts':{name:len(rows) for name,rows in sets.items()},
  'torch_version':torch.__version__,'training_threads':4,'runtime_threads':2,'history':history,'human_review':'pending'}
 (out/'intent-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 report=ROOT/'output/intent-routing-v3';report.mkdir(parents=True,exist_ok=True)
 (report/'training.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'sealed':True,'best_epoch':best_epoch,'development_axes_exact':best,'delta_sha256':manifest['files']['delta.safetensors']}),flush=True)

if __name__=='__main__':main()
