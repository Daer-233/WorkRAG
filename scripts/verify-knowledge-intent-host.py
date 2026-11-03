"""Run inside LangBot: real Host classes/proxy checks, synthetic local events.

No platform adapter or model answer is invoked; no employee receives messages.
"""
import asyncio
from copy import deepcopy
import json
import logging
from types import SimpleNamespace as NS

from langbot.pkg.agent.runner import resource_builder as rb,query_bridge as qb
from langbot.pkg.agent.runner.host_models import AgentEventEnvelope
from langbot.pkg.agent.runner.session_registry import get_session_registry
from langbot.pkg.plugin.handler import _validate_run_authorization
from langbot_plugin.api.entities.builtin.runner.input import AgentInput
from langbot.pkg.platform.adapters.dingtalk.knowledge_card import intent_host as host
from langbot.pkg.platform.adapters.dingtalk.knowledge_card.streaming import prime


async def main():
    checks={}
    assert rb.AgentResourceBuilder._work_intent_installed and qb.QueryRunBridge._work_intent_installed
    checks['installed_host_hooks']=True
    async def models(*args):return []
    async def tools(*args):return [{'tool_name':'design_search','operations':['call']}]
    async def bases(*args):return [{'kb_id':host.KB,'operations':['retrieve']},{'kb_id':'design','operations':['retrieve']}]
    app=NS(skill_mgr=None,logger=logging.getLogger('intent.verify'))
    builder=rb.AgentResourceBuilder(app)
    builder._build_models_from_binding=models;builder._build_tools_from_binding=tools;builder._build_knowledge_bases_from_binding=bases
    builder._build_skills_from_binding=lambda *a:[{'skill_name':'design-rag'}]
    builder._build_storage_from_binding=lambda *a:{'plugin_storage':True,'workspace_storage':True}
    rb.build_platform_tool_resources=lambda *a:([],{})
    rb.config_schema.uses_host_tools=lambda *a:True
    binding=NS(resource_policy=NS(allowed_platform_tool_names=[]),runner_config={},processor_id=host.PIPELINE,runner_id=host.RUNNER)
    descriptor=NS(permissions=NS(tools=['call']))
    event=AgentEventEnvelope.model_construct(event_id='synthetic-intent-event',workspace_id='intent-test-workspace',
        bot_id=host.BOT,input=AgentInput(text='测试通用问题',contents=[{'type':'text','text':'测试通用问题'}],attachments=[]),delivery=None)
    query=NS(query_id='intent-test-query',workspace_uuid='intent-test-workspace',bot_uuid=host.BOT,pipeline_uuid=host.PIPELINE,
        variables={'_work_intent_route':{'intent':'knowledge'}},pipeline_config={'original':True},user_message=NS(content='测试通用问题'))
    original_config=deepcopy(query.pipeline_config)
    qb.RunnerConfigResolver.resolve_runner_id=lambda *a:host.RUNNER
    qb.QueryEntryAdapter.query_to_event=lambda *a:event
    qb.QueryEntryAdapter.config_to_agent_config=lambda *a:{}
    qb.QueryEntryAdapter.build_adapter_context=lambda *a:{}
    bridge=qb.QueryRunBridge(NS(resolve_one=lambda *a:binding))
    scope=host.Scope(query.query_id,query.workspace_uuid,host.BOT,'daily',False)
    token=host.ACTIVE.set(scope)
    registry=get_session_registry();registered=[]
    try:
        plan=bridge.build_plan(query)
        assert '没有知识库' in plan.event.input.text and query.pipeline_config==original_config
        assert query.user_message.content=='测试通用问题'
        checks['trusted_route_not_user_variable']=True
        checks['canonical_config_and_employee_text_unchanged']=True
        daily=await builder.build_resources_from_binding(None,plan.event,binding,descriptor)
        assert not daily['knowledge_bases'] and not daily['tools'] and not daily['skills']
        scope.intent='knowledge'
        work=await builder.build_resources_from_binding(None,plan.event,binding,descriptor)
        assert [k['kb_id'] for k in work['knowledge_bases']]==[host.KB] and not work['skills']
        checks['daily_snapshot_empty_business_resources']=True
        checks['business_snapshot_work_kb_only']=True
        for name,resources in [('daily',daily),('work',work)]:
            run_id='intent-synthetic-'+name
            await registry.register(run_id,host.RUNNER,None,'langbot-team/CodexAgent',resources,
                workspace_id='intent-test-workspace',bot_id=host.BOT)
            registered.append(run_id)
        async def authorized(name,kind,identifier,operation,workspace='intent-test-workspace'):
            session,error=await _validate_run_authorization('intent-synthetic-'+name,kind,identifier,app,
                caller_plugin_identity='langbot-team/CodexAgent',operation=operation,workspace_uuid=workspace)
            return session is not None and error is None
        assert not await authorized('daily','knowledge_base',host.KB,'retrieve')
        assert await authorized('work','knowledge_base',host.KB,'retrieve')
        assert not await authorized('work','knowledge_base','design','retrieve')
        assert not await authorized('work','tool','design_search','call')
        assert not await authorized('work','tool','activate_skill','call')
        assert not await authorized('work','knowledge_base',host.KB,'retrieve',workspace='different-workspace')
        checks['actual_host_proxy_denies_daily_retrieval']=True
        checks['actual_host_proxy_allows_work_retrieval_only']=True
        checks['actual_host_proxy_denies_design_tools_and_skills']=True
        checks['workspace_validation_retained']=True
    finally:
        host.ACTIVE.reset(token)
        for run_id in registered:await registry.unregister(run_id)
    # Selected synthetic event exercises the installed shadow bridge HTTP call.
    query.launcher_type='person';query.launcher_id='intent-synthetic-person';query.sender_id='intent-synthetic-person'
    query.session=NS(using_conversation=NS(uuid='intent-synthetic-conversation'));query.message_chain=[]
    seen=[]
    async def results():
        seen.append(True);yield NS(all_content='合成回答',is_final=True,provider_specific_fields={})
    stream=prime(results(),query,lambda **value:NS(**value))
    ack=await anext(stream)
    assert ack.content=='正在处理' and not seen
    value=await anext(stream)
    assert value.all_content=='合成回答' and host.ACTIVE.get() is None
    try:await anext(stream)
    except StopAsyncIteration:pass
    checks['immediate_ack_before_classification_and_runner']=True
    checks['shadow_preserves_original_stream']=True
    await asyncio.gather(*list(host.SHADOW_TASKS))
    checks['shadow_http_probe_finished']=True
    # Exercise on-mode routing only in this isolated test interpreter; never
    # modify the live Host/backend switch or a real employee conversation.
    host.settings=lambda:{'mode':'on','version':'synthetic'}
    async def classified(payload):return {'mode':'on','config_version':'synthetic','intent':'daily','has_image':False}
    host.classify=classified
    async def routed():
        assert host.ACTIVE.get().intent=='daily'
        plan=bridge.build_plan(query)
        resources=await builder.build_resources_from_binding(None,plan.event,binding,descriptor)
        assert not resources['knowledge_bases'] and not resources['tools'] and not resources['skills']
        yield NS(all_content='日常合成增量',is_final=True,provider_specific_fields={})
    chunks=[chunk async for chunk in prime(routed(),query,lambda **value:NS(**value))]
    assert chunks[0].content=='正在处理' and chunks[-1].all_content=='日常合成增量' and host.ACTIVE.get() is None
    checks['synthetic_on_scope_reaches_real_host_builder']=True
    async def classified_image(payload):return {'mode':'on','config_version':'synthetic','intent':'images','has_image':True}
    host.classify=classified_image
    async def image_route():
        plan=bridge.build_plan(query)
        resources=await builder.build_resources_from_binding(None,plan.event,binding,descriptor)
        assert [kb['kb_id'] for kb in resources['knowledge_bases']]==[host.KB]
        assert '没有读取员工上传图片' in plan.event.input.text
        yield NS(all_content='图片路径合成增量',is_final=True,provider_specific_fields={})
    chunks=[chunk async for chunk in prime(image_route(),query,lambda **value:NS(**value))]
    checks['synthetic_image_route_work_kb_only_and_vision_disclosure']=True
    print(json.dumps({'passed':all(checks.values()),'checks':checks,'employee_messages_sent':0},ensure_ascii=False))


if __name__=='__main__':asyncio.run(main())
