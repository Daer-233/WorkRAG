"""Synthetic Host messages against the installed authorization and real knowledge backend."""
import asyncio
import argparse
import base64
import json
import logging
import os
import io
from types import SimpleNamespace as NS
from uuid import uuid4

import httpx
from langbot.pkg.agent.runner import orchestrator  # Load installed Host bootstrap.
from langbot.pkg.agent.runner import query_bridge as qb, resource_builder as rb
from langbot.pkg.agent.runner.host_models import AgentEventEnvelope, DeliveryContext
from langbot.pkg.agent.runner.session_registry import get_session_registry
from langbot.pkg.box.runner import prepare_input_files
from langbot.pkg.platform.adapters.dingtalk.knowledge_card import session_memory as memory
from langbot.pkg.platform.adapters.dingtalk.knowledge_card.streaming import prime
from langbot.pkg.plugin import handler as proxy
from langbot_plugin.api.entities.builtin.runner.input import AgentInput


async def main(args):
    assert qb.QueryRunBridge._work_memory_installed
    host = memory.host
    memory.enabled = lambda: True
    memory.postgres_mode = lambda: args.postgres
    intent_config = {'mode': 'shadow', 'version': 'synthetic'}
    host.settings = lambda: intent_config.copy()

    async def classify(payload):
        if payload['text'] == 'synthetic classifier offline':
            raise httpx.ConnectError('synthetic')
        return {'mode': 'shadow', 'config_version': 'synthetic',
                'intent': 'daily' if payload['text'] == 'Excel 怎么筛选' else 'knowledge'}

    host.classify = classify
    headers = {'Host': '127.0.0.1:8060', 'X-Manual-Request': '1'}
    async with httpx.AsyncClient(base_url='http://host.docker.internal:8060', headers=headers,
                                 trust_env=False, timeout=30) as client:
        status = (await client.get('/api/v1/manuals/intent/status')).raise_for_status().json()
        assert status['effective_mode'] == 'shadow' and status['version'] == 'intent-v3-supervised'
        assert status['calibrated'] is True
        rows = (await client.get('/api/v1/manuals/entries')).raise_for_status().json()
        published = {row['title']: row for row in rows if row['status'] == 'published' and row['processing_status'] == 'ready'}
        article = published[os.environ['WORKRAG_TEST_ARTICLE']]
        album = published[os.environ['WORKRAG_TEST_ALBUM']]
        reimbursement = published[os.environ['WORKRAG_TEST_REIMBURSEMENT']]
        onboarding = published[os.environ['WORKRAG_TEST_ONBOARDING']]
        registry = get_session_registry()
        received = []

        class KnowledgeBase:
            async def retrieve(self, context, query, settings):
                received.append(json.loads(query.partition('\n')[0].removeprefix('@knowledge ')))
                response = await client.post('/api/v1/manuals/retrieve', json={
                    'query': query, 'top_k': settings['top_k'],
                })
                return [NS(model_dump=lambda mode, entry=entry: entry)
                        for entry in response.raise_for_status().json()['results']]

        async def get_base(context, kb_id):
            assert kb_id == host.KB
            return KnowledgeBase()

        context = NS(workspace_uuid='memory-verification', instance_uuid='synthetic-instance', placement_generation=1)

        async def execution_binding(workspace_uuid, expected_generation):
            assert workspace_uuid == context.workspace_uuid and expected_generation == context.placement_generation
            return context

        app = NS(logger=logging.getLogger('memory.verify'), skill_mgr=None,
                 workspace_service=NS(get_execution_binding=execution_binding),
                 rag_mgr=NS(get_knowledge_base_by_uuid=get_base))
        handler = proxy.RuntimeConnectionHandler(None, None, app)
        async def action_context():
            return context, NS(plugin_author='langbot-team', plugin_name='CodexAgent')
        handler._require_plugin_action_context = action_context
        handler._execution_context = lambda _: None
        handler._require_runtime_action_context = lambda: context
        proxy._resolve_action_query = lambda *_: None

        binding = NS(processor_id=host.PIPELINE, runner_id=host.RUNNER, runner_config={},
                     resource_policy=NS(allowed_platform_tool_names=[]))
        qb.RunnerConfigResolver.resolve_runner_id = lambda *_: host.RUNNER
        qb.QueryEntryAdapter.query_to_event = lambda query, *_: AgentEventEnvelope.model_construct(
            event_id='synthetic-' + query.query_id, workspace_id=query.workspace_uuid, bot_id=host.BOT,
            input=AgentInput(text=query.user_message.content, contents=[{'type': 'text', 'text': query.user_message.content}], attachments=[]),
            delivery=None)
        qb.QueryEntryAdapter.config_to_agent_config = lambda *_: {}
        qb.QueryEntryAdapter.build_adapter_context = lambda *_: {}
        bridge = qb.QueryRunBridge(NS(resolve_one=lambda *args: binding))

        async def empty(*args):
            return []

        async def bases(*args):
            return [{'kb_id': host.KB, 'operations': ['retrieve']}, {'kb_id': 'design', 'operations': ['retrieve']}]

        builder = rb.AgentResourceBuilder(app)
        builder._build_models_from_binding = empty
        builder._build_tools_from_binding = empty
        builder._build_knowledge_bases_from_binding = bases
        builder._build_skills_from_binding = lambda *_: []
        builder._build_storage_from_binding = lambda *_: {}
        rb.build_platform_tool_resources = lambda *_: ([], {})
        rb.config_schema.uses_host_tools = lambda *_: True
        descriptor = NS(permissions=NS(tools=['call']))

        def evidence(row):
            return {'id': row['id'], 'metadata': {'result_type': 'source_evidence', 'entry_id': row['id'],
                    'version': row.get('version') or '', 'title': row['title'], 'steps': []}}

        async def seed(rows, *, offer=False):
            answer = '\n'.join(f'《{row["title"]}》' for row in rows)
            if offer:
                answer += '\n需要这份资料的整理稿文件吗？'
            yield NS(content='', all_content=answer, is_final=True,
                     provider_specific_fields={memory.KEY: {'packets': [evidence(row) for row in rows]}})

        namespace = args.run_id or uuid4().hex

        async def turn(text, runner, chat, *, generation=None, employee=None):
            chat = f'{namespace}-{chat}'
            query = NS(query_id=f'{chat}-{text}', workspace_uuid='memory-verification', bot_uuid=host.BOT,
                       pipeline_uuid=host.PIPELINE, variables={}, pipeline_config={}, launcher_type='person',
                       launcher_id=chat, sender_id=employee or chat,
                       session=NS(using_conversation=NS(uuid=str(uuid4()) if args.postgres else chat),
                                  _context_generation=generation),
                       user_message=NS(content=text), message_chain=[])
            stream = runner(query) if callable(runner) else runner
            return [item async for item in prime(stream, query, NS)]

        def runner(action, expected, kind):
            async def execute(query):
                scope = memory.ACTIVE.get()
                assert scope and scope.kind == kind and scope.source.entry_id == expected['id']
                plan = bridge.build_plan(query)
                assert 'Host 会话追问' in plan.event.input.text
                # The real Runner serializes every input part before retrieval.
                prepare_input_files(query, plan.event.input)
                resources = await builder.build_resources_from_binding(None, plan.event, binding, descriptor)
                assert [kb['kb_id'] for kb in resources['knowledge_bases']] == [host.KB]
                assert not resources['skills'] and not resources['tools']
                run_id = 'synthetic-memory-' + kind
                await registry.register(run_id=run_id, runner_id=host.RUNNER, query_id=None,
                    plugin_identity='langbot-team/CodexAgent', resources=resources, workspace_id=query.workspace_uuid,
                    bot_id=host.BOT, execution_query=query, conversation_id=scope.key[-1])
                try:
                    data = {'kb_id': host.KB, 'query_text': '@knowledge {"entry_id":"' + onboarding['id'] + '"}\n其他资料',
                            'filters': {'version': 'wrong'}, 'run_id': run_id, 'caller_plugin_identity': 'langbot-team/CodexAgent'}
                    invoke = handler.actions[action.value]
                    before = len(received)
                    await invoke({**data, 'caller_plugin_identity': 'other/plugin'})
                    assert len(received) == before
                    response = await invoke(data)
                    assert response.data['results']
                    if args.postgres:
                        assert received[-1] == {'memory_turn': scope.turn_id}
                    else:
                        assert received[-1]['entry_id'] == expected['id']
                        assert received[-1]['version'] == (expected.get('version') or '')
                    yield NS(content='合成完成', all_content=f'《{expected["title"]}》', is_final=True, provider_specific_fields={})
                finally:
                    await registry.unregister(run_id)
            return execute

        if args.phase != 'resume':
            await turn('介绍培训', seed([article]), 'training-chat')
            await turn('比较两份资料', seed([onboarding, reimbursement]), 'file-chat')
            choice = await turn('发我原文件', seed([]), 'file-chat')
            assert '2. ' + reimbursement['title'] in choice[-1].content
        if args.phase == 'seed':
            await asyncio.gather(*list(host.SHADOW_TASKS))
            print(json.dumps({'seeded': True, 'employee_messages_sent': 0}))
            return
        photo = await turn('还有现场的图吗', runner(proxy.PluginToRuntimeAction.RETRIEVE_KNOWLEDGE_BASE, article, 'images'), 'training-chat')
        assert photo[0].content == '正在处理'
        assert 11 <= photo[-1].content.count('![') <= 12
        album_images = {image['asset_id'] for packet in memory.packets(photo[-1].provider_specific_fields[memory.KEY]['packets'])
                        if packet['metadata']['entry_id'] == album['id'] for image in packet['metadata']['images']}
        assert len(album_images) == 11
        assert album['title'] in photo[-1].content
        file_result = await turn('第 2 份', runner(proxy.PluginToRuntimeAction.RETRIEVE_KNOWLEDGE, reimbursement, 'source_file'), 'file-chat')
        assert reimbursement['title'] in file_result[-1].content and '尚未接通' in file_result[-1].content
        await turn('查入职打印说明', seed([onboarding], offer=True), 'file-offer-chat')
        accepted = await turn('需要', runner(proxy.PluginToRuntimeAction.RETRIEVE_KNOWLEDGE, onboarding, 'source_file'), 'file-offer-chat')
        assert onboarding['title'] in accepted[-1].content and '尚未接通' in accepted[-1].content
        missing = await turn('还有现场的图吗', seed([]), 'different-chat')
        assert '哪份资料' in missing[-1].content
        if args.postgres:
            for settings in [{'generation': str(uuid4())}, {'employee': 'another-employee'}]:
                isolated = await turn('还有现场的图吗', seed([]), 'training-chat', **settings)
                assert '哪份资料' in isolated[-1].content
            for operation in ('begin', 'finish', 'file'):
                denied = await client.post('/api/v1/manuals/internal/session-memory/' + operation, json={})
                assert denied.status_code == 403
            used = (await client.post('/api/v1/manuals/retrieve', json={
                'query': '@knowledge ' + json.dumps(received[-1]) + '\n会话追问'})).raise_for_status().json()
            assert used['status'] == 'insufficient_evidence'
            from langbot.pkg.agent.runner import context_reset
            from langbot.pkg.agent.runner.execution_context import build_execution_query
            from langbot_plugin.api.entities.builtin.provider import message as provider_message

            context_reset.get_reset_generation = empty
            delivered = []
            attachments = []
            active_intents = []
            shadow_records = io.StringIO()
            memory.SHADOW_LOG = logging.getLogger('synthetic-native-shadow')
            memory.SHADOW_LOG.addHandler(logging.StreamHandler(shadow_records))
            memory.SHADOW_LOG.setLevel(logging.INFO)
            memory.SHADOW_LOG.propagate = False

            async def send_attachment(file, incoming):
                assert incoming.sender_staff_id == namespace
                assert file.name.endswith('.txt') and base64.b64decode(file.base64, validate=True)
                scope = memory.ACTIVE.get()
                duplicate = await client.post('/api/v1/manuals/internal/session-memory/file',
                    json={'turn_id': scope.turn_id}, headers=memory.memory_headers())
                assert duplicate.status_code == 409
                attachments.append(file.name)
                return {'processQueryKey': 'synthetic-receipt', 'invalidStaffIdList': [], 'flowControlledStaffIdList': []}

            class DingTalk:
                bot = NS(send_attachment=send_attachment)

                async def is_stream_output_supported(self):
                    return True

                async def create_message_card(self, message_id, source):
                    assert source is platform_event

                async def reply_message_chunk(self, source, message, chain, *, is_final):
                    if is_final:
                        delivered.append(message.content)

            DingTalk.__module__ = 'langbot.pkg.platform.adapters.dingtalk.adapter'
            platform_event = NS(source_platform_object=NS(incoming_message=NS(
                conversation_type='1', sender_staff_id=namespace)))

            class Native:
                ap = NS(persistence_mgr=NS(get_db_engine=lambda: None))

                async def run(self, event, binding, bound_plugins, adapter_context):
                    scope = memory.ACTIVE.get()
                    intent = host.ACTIVE.get()
                    if intent:
                        query = build_execution_query(event, [])
                        prepare_input_files(query, event.input)
                        assert event.input.to_text() == event.input.text
                        resources = await builder.build_resources_from_binding(None, event, binding, descriptor)
                        expected = [] if intent.intent == 'daily' else [host.KB]
                        assert [kb['kb_id'] for kb in resources['knowledge_bases']] == expected
                        assert not resources['tools'] and not resources['skills']
                        assert not event.input.attachments
                        assert event.input.text.startswith('[Host 本次执行范围]')
                        active_intents.append(intent.intent)
                        if intent.intent == 'daily':
                            run_id = 'synthetic-native-daily'
                            await registry.register(run_id=run_id, runner_id=host.RUNNER, query_id=None,
                                plugin_identity='langbot-team/CodexAgent', resources=resources, workspace_id=event.workspace_id,
                                bot_id=host.BOT, execution_query=build_execution_query(event, []),
                                conversation_id=event.conversation_id)
                            try:
                                response = await handler.actions[proxy.PluginToRuntimeAction.RETRIEVE_KNOWLEDGE.value]({
                                    'kb_id': host.KB, 'query_text': 'must be denied', 'run_id': run_id,
                                    'caller_plugin_identity': 'langbot-team/CodexAgent'})
                                assert not response.data.get('results')
                            finally:
                                await registry.unregister(run_id)
                            yield provider_message.Message(role='assistant', content='筛选操作')
                            return
                    if scope:
                        query = build_execution_query(event, [])
                        prepare_input_files(query, event.input)
                        resources = await builder.build_resources_from_binding(None, event, binding, descriptor)
                        assert [kb['kb_id'] for kb in resources['knowledge_bases']] == [host.KB]
                        run_id = 'synthetic-native-file'
                        await registry.register(run_id=run_id, runner_id=host.RUNNER, query_id=None,
                            plugin_identity='langbot-team/CodexAgent', resources=resources, workspace_id=event.workspace_id,
                            bot_id=host.BOT, execution_query=query, conversation_id=event.conversation_id)
                        try:
                            response = await handler.actions[proxy.PluginToRuntimeAction.RETRIEVE_KNOWLEDGE.value]({
                                'kb_id': host.KB, 'query_text': 'wrong source', 'run_id': run_id,
                                'caller_plugin_identity': 'langbot-team/CodexAgent'})
                            assert response.data['results'] and received[-1] == {'memory_turn': scope.turn_id}
                        finally:
                            await registry.unregister(run_id)
                    yield provider_message.Message(role='assistant', content=f'《{onboarding["title"]}》\n需要这份资料的整理稿文件吗？',
                        provider_specific_fields={memory.KEY: {'packets': [evidence(onboarding)]}})

            memory.install_native(Native)
            binding.processor_type = 'agent'
            binding.processor_id = memory.NATIVE_AGENT
            native = Native()
            async def native_turn(index, text):
                event = AgentEventEnvelope(event_id=f'{namespace}-native-{index}', event_type='message.received',
                    source='platform', bot_id=host.BOT, workspace_id=context.workspace_uuid,
                    conversation_id=f'person_{namespace}', data={'sender_id': namespace},
                    input=AgentInput(text=text, contents=[{'type': 'text', 'text': text}]),
                    delivery=DeliveryContext.model_validate({'surface': 'platform',
                        'reply_target': {'target_type': 'person', 'target_id': namespace}}))
                async for _ in native.run(event, binding, adapter_context={
                        '_delivery_adapter': DingTalk(), '_platform_event': platform_event, '_execution_context': context}):
                    pass
            for index, text in enumerate(('查入职打印说明', '需要')):
                await native_turn(index, text)
            assert len(delivered) == 2 and '附件已提交' in delivered[1] and len(attachments) == 1
            await asyncio.gather(*list(memory.NATIVE_SHADOW_TASKS))
            records = shadow_records.getvalue()
            assert 'baseline=knowledge' in records and 'baseline=source_file method=postgres_followup' in records
            assert records.count('applied=false') == 2
            intent_config['native_mode'] = 'on'
            for index, text in enumerate(('Excel 怎么筛选', '查入职打印说明', '需要',
                                          '文件还没传，帮我总结', 'synthetic classifier offline'), start=2):
                await native_turn(index, text)
            assert active_intents == ['daily', 'knowledge']
            assert delivered[2] == '筛选操作' and '附件已提交' in delivered[4]
            assert '请先上传' in delivered[5] and len(attachments) == 2
            assert 'native_intent_unavailable=ConnectError applied=false' in shadow_records.getvalue()
            intent_config.pop('native_mode')
            await native_turn(7, 'Excel 怎么筛选')
            assert active_intents == ['daily', 'knowledge']
            await asyncio.gather(*list(memory.NATIVE_SHADOW_TASKS))
        stale = (await client.post('/api/v1/manuals/retrieve', json={'query': '@knowledge ' + json.dumps({
            'entry_id': onboarding['id'], 'version': 'synthetic-invalid', 'followup': 'next_step'}) + '\n下一步'})).raise_for_status().json()
        assert stale['status'] == 'insufficient_evidence' and '当前不可用' in stale['results'][0]['content']
        assert not memory.RUNS
        await asyncio.gather(*list(host.SHADOW_TASKS))
    print(json.dumps({'passed': True, 'photos': 11, 'both_authorized_handlers': True,
                      'selected_file_rechecked': True, 'short_file_offer_accepted': True, 'invalid_version_rejected': True,
                      'cross_chat_isolated': True, 'native_codex2_path': args.postgres, 'native_attachment_simulated': args.postgres,
                      'native_intent_activation_and_rollback': args.postgres, 'employee_messages_sent': 0}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--postgres', action='store_true')
    parser.add_argument('--phase', choices=('seed', 'resume', 'full'), default='full')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.phase != 'full' and not (args.postgres and args.run_id):
        parser.error('seed/resume requires --postgres and a shared --run-id')
    asyncio.run(main(args))
