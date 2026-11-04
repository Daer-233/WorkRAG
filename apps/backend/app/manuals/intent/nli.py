"""Local, pinned NLI process. A timed-out inference is killed, not left running."""
import json
import multiprocessing as mp
from pathlib import Path
import threading
import time

from .settings import digest

HYPOTHESES={
    'daily':'用户需要闲聊、通用知识解释或对已提供文字进行润色，不是在询问本公司的制度、资料或内部流程。',
    'knowledge':'用户需要查询本公司的考勤、入职、人力行政、IT权限、财务报销等内部知识或规定。',
    'images':'用户要从已有培训或工作资料中查找、展示照片、截图或配图。',
    'source_file':'用户希望获取、下载或发送一份现有资料的原文件、模板或整理稿文件。',
    'clarify':'用户没有说明具体问题，或指代缺少足够上下文，需要先补充信息才能处理。',
}


def entailment_index(config):
    found={int(k) for k,v in (getattr(config,'id2label',{}) or {}).items()
           if str(v).casefold() in ('entailment','entail','蕴含')}
    if len(found)!=1: raise ValueError('NLI entailment label is missing or ambiguous')
    return found.pop()


def worker(pipe, model_path):
    try:
        folder=Path(model_path);manifest=json.loads((folder/'intent-manifest.json').read_text(encoding='utf-8'))
        if not manifest.get('files'): raise ValueError('Empty intent model manifest')
        for name,expected in manifest['files'].items():
            file=(folder/name).resolve()
            if not file.is_relative_to(folder.resolve()) or digest(file)!=expected: raise ValueError('Intent model checksum mismatch')
        import torch
        from transformers import AutoModelForSequenceClassification,AutoTokenizer
        torch.set_num_threads(2);torch.set_num_interop_threads(1)
        tokenizer=AutoTokenizer.from_pretrained(folder,local_files_only=True,trust_remote_code=False)
        model=AutoModelForSequenceClassification.from_pretrained(folder,local_files_only=True,trust_remote_code=False).eval()
        entail=entailment_index(model.config)
        # First forward can initialize CPU kernels. Finish warming before ready;
        # serving inference still has an independent two-second hard deadline.
        encoded=tokenizer(['测试本公司考勤问题']*5,list(HYPOTHESES.values()),
            padding=True,truncation='only_first',max_length=256,return_tensors='pt')
        with torch.inference_mode():
            for _ in range(2):model(**encoded)
        pipe.send({'ready':True})
        while True:
            request=pipe.recv()
            if request is None:break
            labels=list(HYPOTHESES)
            encoded=tokenizer([request]*len(labels),[HYPOTHESES[label] for label in labels],
                padding=True,truncation='only_first',max_length=256,return_tensors='pt')
            with torch.inference_mode(): values=model(**encoded).logits.softmax(-1)[:,entail].tolist()
            pipe.send({'scores':dict(zip(labels,values))})
    except (EOFError,BrokenPipeError): pass
    except Exception as exc:
        try:pipe.send({'error':type(exc).__name__})
        except (EOFError,BrokenPipeError):pass
    finally:pipe.close()


class BertWorker:
    def __init__(self, model_path, target=None):
        self.model_path=str(model_path);self.lock=threading.Lock()
        self.target=target or worker
        self.process=None;self.pipe=None;self.ready=False;self.error='not_loaded'

    def start(self, timeout=180):
        with self.lock:
            if self.ready and self.process and self.process.is_alive():return True
            self._stop()
            context=mp.get_context('spawn');parent,child=context.Pipe()
            self.pipe=parent;self.process=context.Process(target=self.target,args=(child,self.model_path),daemon=True)
            self.process.start();child.close()
            if not parent.poll(timeout):self.error='model_load_timeout';self._stop();return False
            try:result=parent.recv()
            except (EOFError,OSError):result={'error':'model_process_closed'}
            self.ready=result.get('ready',False);self.error=result.get('error','')
            if not self.ready:self._stop()
            return self.ready

    def classify(self,text,timeout=2):
        if not self.lock.acquire(blocking=False):raise RuntimeError('nli_busy')
        try:
            if not self.ready or not self.process or not self.process.is_alive():raise RuntimeError(self.error or 'nli_not_ready')
            self.pipe.send(text)
            if not self.pipe.poll(timeout):
                self.error='nli_timeout';self._stop(quick=True);raise TimeoutError('nli_timeout')
            result=self.pipe.recv()
            if 'scores' not in result:
                self.error=result.get('error','nli_failed');self._stop(quick=True);raise RuntimeError(self.error)
            return result['scores']
        finally:self.lock.release()

    def _stop(self,quick=False):
        self.ready=False
        if self.process:
            if self.process.is_alive():self.process.kill() if quick else self.process.terminate()
            self.process.join(timeout=.2 if quick else 3)
            if self.process.is_alive():self.process.kill();self.process.join(timeout=3)
        if self.pipe:self.pipe.close()
        self.process=None;self.pipe=None

    def close(self):
        with self.lock:self._stop()
