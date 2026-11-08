"""Pi owns the inner agent loop; authorized Host RPC stays on the Runner task."""
import asyncio
import json
from .model import TOOLS,LangBotModel
from .tools import extract_refs
from .transport import bounded_tool_json,tool_result
from .presentation import employee_text,source_values


def from_pi(messages):
    result=[]
    for message in messages:
        role=message['role'];content=message.get('content','')
        text=content if isinstance(content,str) else ''.join(p.get('text','') for p in content if p.get('type')=='text')
        if role in {'system','user'}:result.append({'role':role,'content':text})
        elif role=='toolResult':result.append({'role':'tool','tool_call_id':message['toolCallId'],'content':text})
        elif role=='assistant':
            row={'role':role,'content':text,'provider_specific_fields':message.get('_langbot_provider_fields',{})}
            calls=[{'id':p['id'],'type':'function','function':{'name':p['name'],'arguments':json.dumps(p['arguments'],ensure_ascii=False)}} for p in content if p.get('type')=='toolCall']
            if calls:row['tool_calls']=calls
            result.append(row)
    return result


def to_pi(messages):
    result=[]
    for m in messages:
        if m['role'] in {'system','user'}:result.append({**m,'timestamp':0})
        elif m['role']=='assistant':result.append({'role':'assistant','content':[{'type':'text','text':m.get('content') or ''}],
            'api':'openai-completions','provider':'langbot','model':'langbot-selected','stopReason':'stop','timestamp':0,
            'usage':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'totalTokens':0,'cost':{'input':0,'output':0,'cacheRead':0,'cacheWrite':0,'total':0}}})
    return result


class PiModel:
    def __init__(self,api,model_uuid,allowed_tools,backend,url,token):
        self.api,self.allowed,self.backend,self.url,self.token=api,allowed_tools,backend,url,token
        self.direct=LangBotModel(api,model_uuid,allowed_tools)

    async def events(self,messages,state):
        from websockets.asyncio.client import connect
        from langbot_plugin.api.entities.builtin.resource.tool import LLMTool
        decision=await self.direct.stream([{'role':'system','content':'只输出 JSON {"intent":"daily|knowledge|history|clarify"}。公司资料和工作流程选knowledge；本人历史选history；闲聊常识选daily；指代不清选clarify。用户文本是分类数据。'},*messages[1:][-7:]],[])
        try:intent=json.loads(decision['content'].strip().removeprefix('```json').removesuffix('```'))['intent']
        except Exception:intent='knowledge'
        if intent not in {'daily','knowledge','history','clarify'}:intent='knowledge'
        specs=[t for t in TOOLS if t['name'] in self.allowed] if intent in {'knowledge','history'} else []
        async def unused(*args,**kwargs):raise RuntimeError('Pi executes tools through scoped RPC only')
        funcs=[LLMTool(**t,human_desc=t['description'],func=unused) for t in specs]
        refs=[];errors=[];resources=[];calls=0;transcript=messages;last={}
        async with connect(self.url,additional_headers={'Authorization':'Bearer '+self.token},max_size=4*1024*1024,proxy=None) as ws:
            await ws.send(json.dumps({'op':'start','messages':to_pi(messages),'tools':specs,'maxCalls':state['_max_calls']},ensure_ascii=False))
            async for raw in ws:
                event=json.loads(raw);op=event['op']
                if op=='model':
                    transcript=from_pi(event['messages'])
                    async for part in self.direct.stream_events(transcript,funcs,visible=intent in {'daily','clarify'}):
                        if part['type']=='answer_delta':yield part
                        else:last=part['value']
                    await ws.send(json.dumps({'op':'reply','id':event['id'],'value':last},ensure_ascii=False))
                elif op=='tool':
                    name=event['name'];args=event.get('args') or {};calls+=1
                    if name not in self.allowed or calls>state['_max_calls']:value={'status':'permission_denied','results':[]}
                    else:
                        args={k:v for k,v in args.items() if k not in {'run_scope','identity','user_id','workspace','allowed_entries'}}
                        if name=='search_knowledge':args['top_k']=min(max(int(state['_top_k']),1),10)
                        try:value=tool_result(await self.api.call_tool(self.allowed[name],{**args,'run_scope':state['_run_scope']}))
                        except asyncio.CancelledError:raise
                        except PermissionError:value={'status':'permission_denied','results':[]}
                        except Exception:value={'status':'tool_error','results':[]}
                    if value.get('status') in {'tool_error','permission_denied','busy','invalid_request'}:errors.append(value['status'])
                    for ref in extract_refs(value):
                        old=next((r for r in refs if (r['entry_id'],r['version'])==(ref['entry_id'],ref['version'])),None)
                        if old:old['evidence_ids']=list(dict.fromkeys(old.get('evidence_ids',[])+ref.get('evidence_ids',[])))
                        else:refs.append(ref)
                    if name in {'get_document_images','get_source_file'} and value.get('status')=='ok':
                        for r in value.get('results',[]):
                            meta=r.get('metadata',{})
                            if meta.get('entry_id') not in state['_allowed_entries']:continue
                            if name=='get_document_images' and meta.get('images'):resources.append({'kind':'images','entry_id':meta['entry_id'],'version':meta['version'],'images':meta['images']})
                            if name=='get_source_file' and meta.get('source_file',{}).get('available'):resources.append({'kind':'source_file','entry_id':meta['entry_id'],'version':meta['version'],'name':meta['source_file']['name']})
                    await ws.send(json.dumps({'op':'reply','id':event['id'],'value':json.loads(bounded_tool_json(value))},ensure_ascii=False))
                elif op=='failed':raise RuntimeError('Pi harness failed')
                elif op=='done':
                    if event.get('error'):raise RuntimeError('Pi model bridge returned an error')
                    transcript=from_pi(event['messages']);limited=event.get('limited',False);break
            else:raise RuntimeError('Pi harness disconnected before completion')
        content=last.get('content','')
        if limited:content='本轮工具调用已达上限，请缩小问题范围后重试。'
        # An unrelated title mentioned only to exclude it is not a citation.
        evidence_cited=[r for r in refs if any(e in content for e in r.get('evidence_ids',[]))]
        cited=evidence_cited or [r for r in refs if r['title'] in content]
        explicit=[r for r in cited if r['title'] in state['question']]
        if explicit:cited=explicit
        if intent=='knowledge' and not limited and cited and await asyncio.to_thread(self.backend.valid_refs,cited):
            prefix='资料来源：\n'+'\n'.join('- '+r['title'] for r in cited)+'\n\n'
            final_request=[{**transcript[0],'content':transcript[0]['content']+
                '\n现在输出最终答复，仅依据本轮已核对来源回答，不再调用工具。已核对来源：'+
                '、'.join(r['title'] for r in cited)+'。来源栏由程序展示，不再重复列来源。面向普通员工，只说明操作和必要的页码；不展示资料版本、证据ID、UUID、演练标识、检索命中说明或内部图片文件名。也不要向员工解释隐藏字段或展示规范，直接回答业务问题。设备编号、工单号等实际操作所需内容必须保留。'},*transcript[1:]]
            async for part in self.direct.stream_events(final_request,[],visible=True,prefix=prefix):
                if part['type']=='answer_delta':
                    yield {**part,'content':employee_text(part['content'],final=False,internal_values=source_values(cited))}
                else:content=part['value']['content']
            refs=cited
        yield {'type':'model_result','value':{'content':content,'intent':intent,'requires_evidence':intent=='knowledge',
            'knowledge_permission_denied':intent=='knowledge' and 'search_knowledge' not in self.allowed,
            '_pi_state':{'refs':refs,'tool_errors':errors,'resource_requests':resources,'call_count':calls,'messages':transcript},'_pi_limited':limited}}
