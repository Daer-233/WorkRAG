"""Offline CPU feasibility probe; no model/data mutation."""
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/backend'))
os.environ['DESIGN_RAG_ENV_FILE']=str(ROOT/'instances/manuals/.env')
from dotenv import load_dotenv
load_dotenv(ROOT/'instances/manuals/.env',override=True)


def main():
    started=time.monotonic()
    import torch
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    from transformers import AutoTokenizer
    from app.manuals.intent.supervised import build_network
    base=ROOT/'data/manuals/models/intent/erlangshen-110m-nli'
    model=build_network(base);tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True)
    model.eval();model.tune_last_layer()
    print('loaded_seconds',round(time.monotonic()-started,2),flush=True)
    encoded=tokenizer(['请查本公司补卡申请流程','Excel 表格如何筛选']*4,padding=True,return_tensors='pt')
    for i in range(2):
        t=time.monotonic()
        with torch.no_grad():hidden=model.lower(encoded)
        print('cache_batch8_seconds',round(time.monotonic()-t,3),flush=True)
    model.train();optimizer=torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],lr=2e-5)
    t=time.monotonic();out=model.upper(hidden,encoded['attention_mask']);loss=sum(v.square().mean() for v in out.values());loss.backward();optimizer.step()
    print('train_top_batch8_seconds',round(time.monotonic()-t,3),flush=True)
    model.eval();torch.set_num_threads(2)
    single=tokenizer('公司电脑权限如何申请',return_tensors='pt')
    for i in range(3):
        t=time.monotonic()
        with torch.inference_mode():model(**single)
        print('runtime_single_seconds',round(time.monotonic()-t,3),flush=True)


if __name__=='__main__':main()
