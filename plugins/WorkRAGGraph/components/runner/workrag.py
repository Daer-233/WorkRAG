import asyncio
import json
import os

from langbot_plugin.api.definition.components.runner import Runner,RunnerContext,RunnerResult
from langbot_plugin.api.entities.builtin.provider.message import Message,MessageChunk
from workrag_agent.graph import Workflow
from workrag_agent.store import Store
from workrag_agent.model import LangBotModel,SimulationModel,TOOLS
from workrag_agent.tools import Backend
from workrag_agent.bridge import InvocationBridge
from workrag_agent.transport import tool_result
from workrag_agent.presentation import employee_text,source_values


def identity(ctx,processor):
    conversation=ctx.conversation
    if conversation is None or not ctx.actor or not ctx.actor.actor_id:
        raise ValueError('Authenticated user conversation required')
    return {'workspace':conversation.workspace_id or str(ctx.runtime.metadata.get('workspace_uuid','')),
            'bot':conversation.bot_id or 'langbot-debug',
            'processor':processor,
            'conversation':conversation.conversation_id or conversation.session_id,
            'sender':ctx.actor.actor_id}


class WorkRAGRunner(Runner):
    async def run(self,ctx:RunnerContext):
        try:
            api=self.get_run_api(ctx)
            ledger=await api.run_get()
            ident=identity(ctx,ledger.agent_id or ledger.binding_id)
            private=self.get_plugin_config()
            if ident['workspace']!=private.get('workspace'): raise PermissionError('Workspace is not authorized')
            store=Store(private['database_dsn'])
            if ctx.event.event_type=='feedback.received':
                from langbot_plugin.api.entities.builtin.platform.events import FeedbackReceivedEvent
                event=FeedbackReceivedEvent.model_validate({**ctx.event.data,'type':'feedback.received'})
                with store.connection() as c:
                    row=c.execute('SELECT id FROM wa_answers WHERE workspace=%s AND (card_id=%s OR id::text=%s)',
                                  (ident['workspace'],event.message_id,event.message_id)).fetchone()
                if not row: raise ValueError('Feedback does not identify a stored answer')
                await asyncio.to_thread(store.feedback,ident,event.feedback_id,str(row['id']),
                    {1:'positive',2:'negative',3:'unknown'}.get(event.feedback_type,'unknown'),event.feedback_content or '')
                yield RunnerResult.run_completed(ctx.run_id)
                return
            config=dict(ctx.config)
            if config.get('engine','legacy') not in {'pi','legacy'}:
                raise ValueError('Agent 引擎只能填写 pi 或 legacy。')
            allowed=json.loads(config.get('allowed_entry_ids','[]'))
            if not isinstance(allowed,list) or not all(isinstance(x,str) for x in allowed): raise ValueError('Invalid document allowlist')
            api=self.get_run_api(ctx)
            available=await api.list_tools()
            tool_map={}
            for spec in TOOLS:
                matches=[t for t in available if t['name']==spec['name'] or t['name'].endswith('_'+spec['name'])]
                if len(matches)==1: tool_map[spec['name']]=matches[0]['name']
            bridge=InvocationBridge()
            async def tool_rpc(name,args):
                if name not in tool_map: raise PermissionError('MCP tool is not granted to this runner')
                result=await api.call_tool(tool_map[name],args)
                return tool_result(result)
            async def tool(name,args): return await bridge.call(tool_rpc,name,args)
            if config.get('simulation'):
                model=SimulationModel()
            else:
                model_id=config.get('model')
                if not model_id: raise ValueError('请先在 LangBot 配置外部 API 模型并在运行器中选择；或显式启用模拟验收。')
                if model_id not in await api.get_llm_models(): raise PermissionError('Selected model is not granted')
                if config.get('engine','legacy')=='pi':
                    from workrag_agent.pi_model import PiModel
                    model=PiModel(api,model_id,tool_map,Backend('http://host.docker.internal:8060'),
                        private.get('pi_harness_url','ws://host.docker.internal:8062/run'),private.get('pi_harness_token',''))
                else:model=LangBotModel(api,model_id,tool_map)
            direct_model=model
            async def model(messages,state):
                return await bridge.call(getattr(direct_model,'events',direct_model),messages,state)
            # An empty first chunk makes Host create the native waiting card.
            # Sending placeholder text here would immediately advance DingTalk
            # flowStatus from 1 (spinner) to 2 (answer streaming).
            yield RunnerResult.message_delta(ctx.run_id,MessageChunk(role='assistant',content='',all_content=''))
            backend=Backend('http://host.docker.internal:8060')
            workflow=Workflow(store,backend,model,tool,private['scope_secret'],ident,ctx.event.event_id,allowed,config)
            async for event in bridge.iterate(workflow.run(ctx.input.to_text())):
                if event['type']=='answer_delta':
                    snapshot=employee_text(event['content'],final=False)
                    yield RunnerResult.message_delta(ctx.run_id,MessageChunk(role='assistant',content=snapshot,all_content=snapshot))
                elif event['type']=='workflow_result': result=event['value']
            answer=result['answer']
            parts=[]
            if result.get('resource_requests'):
                from workrag_agent.media import prepare_media
                try:
                    parts,notes=await asyncio.to_thread(prepare_media,backend,result['resource_requests'],allowed)
                    if notes:answer+='\n\n'+'\n'.join(notes)
                except Exception:
                    answer+='\n\n附件读取未完成，本轮未附加图片或文件，请稍后重试。'
            answer=employee_text(answer,internal_values=source_values(result.get('refs',[])))
            content=[{'type':'text','text':answer},*parts] if parts else answer
            yield RunnerResult.run_completed(ctx.run_id,message=Message(role='assistant',content=content))
        except asyncio.CancelledError: raise
        except (ValueError,PermissionError) as e:
            yield RunnerResult.run_failed(ctx.run_id,str(e))
        except Exception as e:
            yield RunnerResult.run_failed(ctx.run_id,'工作流暂时不可用（'+type(e).__name__+'），请检查本机服务状态。')
