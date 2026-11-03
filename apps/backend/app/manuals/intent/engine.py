import asyncio
import logging
from logging.handlers import RotatingFileHandler
import re
import time

from .bm25 import BM25, accepted, ranking
from .nli import BertWorker
from .settings import DATA, activation_valid, calibration_valid, config, load_rows
from .terra import TerraClassifier
from .types import Decision, context_text

log=logging.getLogger('work.intent')
if not log.handlers:
    folder=DATA/'intent';folder.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(folder/'routing.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    log.addHandler(handler);log.setLevel(logging.INFO)


def direct(request):
    text=request.text.strip()
    if not text or ('image' in request.attachment_types and text in ('这个','看看这个','看图','这是什么','帮我看看','请看图片')):
        return 'clarify','image_text_missing' if 'image' in request.attachment_types else 'question_missing'
    if file_followup(text):
        if request.previous_file_offer and request.previous_sources:
            return ('source_file','previous_file_offer') if len(request.previous_sources)==1 else ('clarify','choose_source')
        return 'clarify','missing_file_context'
    return None


def file_followup(text):
    return text.rstrip('。！？!?,， ') in ('需要','要','好的要','发给我','发我','给我','需要源文件','要原文件','原文件也给我',
        '把刚才的源文件发我','上一份资料的原件给我','需要上一条的文件')


def message_for(intent,reason,request):
    if reason=='image_text_missing':return '目前还不能读取你上传的图片，请补充具体问题或图片中的报错文字。'
    if reason=='choose_source':return '请确认需要哪份文件：'+ '；'.join(f'{i+1}. {s.title}'+(f'（{s.version}）' if s.version else '') for i,s in enumerate(request.previous_sources))
    if intent=='source_file':
        if len(request.previous_sources)>1:return message_for('clarify','choose_source',request)
        if len(request.previous_sources)==1:
            source=request.previous_sources[0]
            if not source.available:return f'《{source.title}》当前没有可确认的可下载源文件，可以先查看已经引用的文字依据。当前尚未接通附件发送。'
            return f'你需要的是《{source.title}》'+ ('的整理稿。' if source.kind=='extracted_markdown' else '的源文件。')+'当前尚未接通附件发送，可在工作知识助手的资料管理中查看或下载。'
        return '请补充需要的文件名称或资料主题。当前尚未接通附件发送，可先帮你查找对应资料。'
    if intent=='clarify':return '请补充你想了解的问题、资料名称或需要处理的文字。'
    return ''


class Router:
    def __init__(self):
        self.worker=None;self.terra=TerraClassifier();self.warming=None;self.model_path=None;self.retry_after=0

    async def warm(self):
        cfg=config()
        if cfg['mode']=='off':return
        if self.warming and not self.warming.done():return
        if self.worker and self.worker.ready and self.model_path==cfg['model_path']:return
        if time.monotonic()<self.retry_after:return
        self.retry_after=time.monotonic()+60
        async def start():
            if self.worker:await asyncio.to_thread(self.worker.close)
            self.model_path=cfg['model_path'];self.worker=BertWorker(self.model_path)
            try:ready=await asyncio.to_thread(self.worker.start)
            except Exception as exc:
                ready=False;self.worker.error=type(exc).__name__
            log.info('intent_model_ready=%s error=%s',ready,self.worker.error)
        self.warming=asyncio.create_task(start())

    async def close(self):
        if self.warming:await self.warming
        if self.worker:await asyncio.to_thread(self.worker.close)

    async def route(self,request):
        started=time.monotonic();cfg=config();mode=cfg['mode']
        if mode=='on' and not activation_valid(cfg):mode='shadow'
        decision=Decision(method='off' if mode=='off' else 'context',mode=mode,config_version=cfg['version'],has_image='image' in request.attachment_types)
        if mode=='off':return decision
        if not file_followup(request.text):
            request=request.model_copy(update={'previous_sources':[],'previous_file_offer':False})
        result=direct(request);artifact=calibration_valid(cfg);reasons=[]
        if result:decision.intent,decision.reason=result
        if not result and artifact:
            scores=BM25(load_rows('index')).scores(request.text);label,score,gap=ranking(scores)
            decision.scores=scores;decision.margin=gap
            if accepted(scores,artifact.get('bm25',{})):
                decision.intent=label;decision.method='bm25'
        if decision.intent is None:
            await self.warm()
            if artifact and self.worker and self.worker.ready:
                try:
                    scores=await asyncio.to_thread(self.worker.classify,context_text(request),2)
                    label,score,gap=ranking(scores);decision.scores=scores;decision.margin=gap
                    if accepted(scores,artifact.get('nli',{})):
                        decision.intent=label;decision.method='bert_nli'
                    else:reasons.append('nli_below_calibrated_threshold')
                except Exception as exc:
                    reasons.append(type(exc).__name__)
                    if isinstance(exc,TimeoutError):self.retry_after=time.monotonic()+300
            else:reasons.append('calibration_or_model_unavailable')
        decision.local_elapsed_ms=round((time.monotonic()-started)*1000,2)
        if decision.intent is None:
            if cfg['terra_enabled']:
                try:
                    decision.intent=await self.terra.classify(request);decision.method='terra'
                except Exception as exc:
                    decision.intent='clarify';decision.method='fallback';reasons.append(type(exc).__name__)
            else:decision.intent='clarify';decision.method='fallback';reasons.append('terra_disabled')
        # No previous sources are ever invented by a classifier.
        if decision.intent=='source_file' and len(request.previous_sources)>1:
            decision.intent='clarify';decision.reason='choose_source'
        decision.needs_clarification=decision.intent=='clarify'
        decision.message=message_for(decision.intent,decision.reason,request)
        decision.reason=decision.reason or ','.join(reasons)
        decision.elapsed_ms=round((time.monotonic()-started)*1000,2)
        log.info('intent=%s layer=%s mode=%s scores=%s margin=%s elapsed_ms=%s local_ms=%s reason=%s version=%s',
            decision.intent,decision.method,mode,decision.scores,decision.margin,decision.elapsed_ms,
            decision.local_elapsed_ms,decision.reason,cfg['version'])
        return decision


router=Router()
