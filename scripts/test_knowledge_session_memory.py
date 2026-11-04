import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/backend'))
from knowledge_card import session_memory as memory
from knowledge_card.codex_delta import KEY
from knowledge_card.streaming import prime


FIRST = '11111111-1111-4111-8111-111111111111'
SECOND = '22222222-2222-4222-8222-222222222222'
STEP = '33333333-3333-4333-8333-333333333333'


def query(text, *, sender='employee', conversation='conversation', launcher='person', identifier='query'):
    return NS(query_id=identifier, workspace_uuid='work', bot_uuid=memory.host.BOT,
              pipeline_uuid=memory.host.PIPELINE, launcher_type=launcher, launcher_id='chat', sender_id=sender,
              session=NS(using_conversation=NS(uuid=conversation)), user_message=NS(content=text))


def packet(entry, title, *, version='', images=None, available=True):
    return {'id': entry, 'metadata': {'result_type': 'source_evidence', 'entry_id': entry, 'title': title,
            'version': version, 'steps': [{'evidence_ids': [STEP]}], 'images': images or [],
            'source_file': {'available': available, 'kind': 'archived_file'}}}


async def message(text, evidence=()):
    yield NS(content=text, all_content=text, is_final=True, provider_specific_fields={KEY: {'packets': evidence}})


async def run(text, reply=None, **kwargs):
    return [part async for part in prime(reply or message('正常回答'), query(text, **kwargs), NS)]


@pytest.fixture(autouse=True)
def synthetic_host(monkeypatch):
    monkeypatch.setattr(memory, 'enabled', lambda: True)
    async def original(stream, *_):
        async for value in stream:
            yield value
    monkeypatch.setattr(memory.host, 'route_results', original)
    for collection in (memory.MEMORY, memory.IN_FLIGHT, memory.LATEST, memory.RUNS):
        collection.clear()


def test_multi_source_followup_uses_fresh_selected_file_only():
    async def scenario():
        await run('分别查两份报销规定', message('见《差旅规范》和《报销说明》', [
            packet(FIRST, '差旅规范'), packet(SECOND, '报销说明', version='2025')]))
        selection = await run('发我原文件')
        assert '1. 差旅规范' in selection[-1].content and '2. 报销说明（2025）' in selection[-1].content

        async def tool_call():
            scope = memory.ACTIVE.get()
            memory.RUNS['run'] = scope
            scope.runs.add('run')
            session = {'run_id': 'run'}
            text, _, filters = memory.scoped_query(session, memory.host.KB, '@knowledge {"entry_id":"bad"}\nother', 20, {'version': 'wrong'})
            control = json.loads(text.splitlines()[0].removeprefix('@knowledge '))
            assert control['entry_id'] == SECOND and control['version'] == '2025' and filters == {}
            with pytest.raises(ValueError):
                memory.scoped_query(session, 'design', 'test', 5, {})
            memory.capture(session, memory.host.KB, [packet(SECOND, '报销说明', available=False)])
            async for item in message('附件已经发送'):
                yield item

        result = await run('第 2 份', tool_call())
        assert result[0].content == '正在处理'
        assert '《报销说明》目前没有可用' in result[-1].content
        assert all('已经发送' not in part.content for part in result)
        assert not memory.RUNS
    asyncio.run(scenario())


def test_photo_followup_uses_current_verified_media():
    async def scenario():
        await run('培训内容', message('见《培训回顾》', [packet(FIRST, '培训回顾')]))
        async def tool_call():
            scope = memory.ACTIVE.get()
            assert scope.kind == 'images' and scope.source.entry_id == FIRST
            scope.evidence = [packet(SECOND, '培训现场照片', images=[
                {'asset_id': 'photo', 'preview_url': '/api/v1/manuals/assets/photo?access_token=current', 'name': '老师'}])]
            async for item in message('没有照片'):
                yield item
        result = await run('还有现场的图吗', tool_call())
        assert '![老师](/api/v1/manuals/assets/photo?access_token=current)' in result[-1].content
        assert '《培训现场照片》' in result[-1].content
    asyncio.run(scenario())


def test_identity_expiration_and_no_uncited_source():
    async def scenario():
        await run('培训内容', message('见《培训回顾》', [packet(FIRST, '培训回顾'), packet(SECOND, '未引用')]))
        key = memory.identity(query(''))
        assert [source.entry_id for source in memory.MEMORY[key].sources] == [FIRST]
        assert '哪份资料' in (await run('刚才那份', sender='another'))[-1].content
        assert (await run('刚才那份', launcher='group'))[-1].content == '正常回答'
        assert '哪份资料' in (await run('刚才那份', conversation='reset'))[-1].content
        assert key not in memory.MEMORY
        await run('新问题', message('见《培训回顾》', [packet(FIRST, '培训回顾')]))
        assert memory.previous(key, memory.MEMORY[key].at + 1800) is None
        assert '哪份资料' in (await run('发我原文件'))[-1].content
    asyncio.run(scenario())


def test_new_topic_and_concurrent_response_cannot_restore_old_source():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def old():
            started.set()
            await release.wait()
            async for item in message('见《旧资料》', [packet(FIRST, '旧资料')]):
                yield item
        task = asyncio.create_task(run('旧主题', old(), identifier='old'))
        await started.wait()
        assert '还在处理' in (await run('还有现场的图吗'))[-1].content
        await run('新主题', message('见《新资料》', [packet(SECOND, '新资料')]), identifier='new')
        release.set()
        await task
        record = memory.MEMORY[memory.identity(query(''))]
        assert record.sources[0].entry_id == SECOND
    asyncio.run(scenario())


def test_runner_without_fresh_retrieval_cannot_reply_from_old_evidence():
    async def scenario():
        await run('查入职', message(f'见《入职指南》 {STEP}', [packet(FIRST, '入职指南', version='2025')]))
        async def stale():
            assert memory.ACTIVE.get().source.cursor == STEP
            async for item in message('擅自填写下一步'):
                yield item
        result = await run('那下一步呢', stale())
        assert '没有取得' in result[-1].content
        assert len(result) == 2
    asyncio.run(scenario())


def test_next_step_stays_in_same_procedure_and_pinned_version(monkeypatch):
    from app.manuals import session_followup as backend
    from app.manuals.langbot import KnowledgeFilters

    steps = [{'order': 1, 'evidence_id': STEP}, {'order': 2, 'evidence_id': SECOND},
             {'order': 1, 'evidence_id': FIRST}]
    row = {'id': FIRST, 'title': '入职设置', 'status': 'published', 'processing_status': 'ready',
           'version': '2025', 'data': {'steps': steps, 'groups': [
               {'id': 'first', 'start': 0, 'end': 2}, {'id': 'other', 'start': 2, 'end': 3}]}}
    service = NS(store=NS(get=lambda _: row), answer_entry=lambda *args: {'steps': list(steps[:2])})
    monkeypatch.setattr(backend, 'source_result', lambda answer, *_: answer)
    filters = KnowledgeFilters(entry_id=FIRST, version='2025', followup='next_step', cursor=STEP)
    result = backend.retrieve_followup(service, '下一步', filters, 5)
    assert result['results'][0]['steps'] == [steps[1]]
    boundary = filters.model_copy(update={'cursor': SECOND})
    assert backend.retrieve_followup(service, '下一步', boundary, 5)['status'] == 'insufficient_evidence'
    for status, version in [('published', '2026'), ('superseded', '2025')]:
        row.update(status=status, version=version)
        assert backend.retrieve_followup(service, '下一步', filters, 5)['results'][0]['content'] == backend.UNAVAILABLE
