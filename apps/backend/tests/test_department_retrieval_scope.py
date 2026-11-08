from types import SimpleNamespace

from app.manuals.service import ManualService
from app.manuals.session_followup import retrieve_followup
from app.manuals.langbot import KnowledgeFilters
from uuid import uuid4
import json
import pytest
from app.manuals import departments
from app.manuals.langbot import KnowledgeRetrieval, retrieve
from app.manuals import api
from app.services.image_asset_access import sign_asset_access
from fastapi import HTTPException
from app.manuals import session_memory


def test_authorization_filters_before_retrieval_and_cannot_expand_entry_filter():
    entries = [dict(id='one', status='published', processing_status='ready', category_id=None,
                    product='', version=''),
               dict(id='two', status='published', processing_status='ready', category_id=None,
                    product='', version='')]
    seen = []

    class Store:
        def entries(self):
            return entries

    class Retriever:
        def search(self, question, candidates, limit):
            seen.append([item['id'] for item in candidates])
            return SimpleNamespace(mode='test', metrics={}, limitations=[], hits=[])

    service = ManualService(store=Store(), retriever=Retriever())
    service.ask('查询', permitted_entry_ids={'one'})
    service.ask('查询', entry_id='two', permitted_entry_ids={'one'})
    service.ask('查询', permitted_entry_ids=set())
    assert seen == [['one'], [], []]


def test_followup_does_not_return_an_unauthorized_document():
    entry_id = uuid4()
    entry = {'id': entry_id, 'version': '', 'status': 'published', 'processing_status': 'ready'}

    class Store:
        def get(self, key):
            return entry

    service = SimpleNamespace(store=Store())
    filters = KnowledgeFilters(entry_id=entry_id, version='', followup='source_file')
    response = retrieve_followup(service, '原文件', filters, 5, permitted_entry_ids=set())
    assert response['status'] == 'insufficient_evidence'


def test_enforced_connector_rejects_unscoped_regular_and_memory_queries(monkeypatch):
    monkeypatch.setattr(departments, 'enforced', lambda: True)
    service = SimpleNamespace()
    for query in ('公司规定是什么', '@knowledge ' + json.dumps({'memory_turn': str(uuid4())}) + '\n追问'):
        with pytest.raises(ValueError, match='部门授权上下文缺失'):
            retrieve(service, KnowledgeRetrieval(query=query))


def test_scoped_query_passes_authorized_ids_to_retriever(monkeypatch):
    context_id = uuid4()
    monkeypatch.setattr(departments, 'enforced', lambda: True)
    monkeypatch.setattr(departments, 'permitted_for_context', lambda value: {'allowed'} if value == context_id else set())
    received = []

    def ask(**kwargs):
        received.append(kwargs)
        return {'status': 'insufficient_evidence', 'limitations': []}

    query = '@knowledge ' + json.dumps({'department_context': str(context_id)}) + '\n查询'
    retrieve(SimpleNamespace(ask=ask), KnowledgeRetrieval(query=query))
    assert received[0]['permitted_entry_ids'] == {'allowed'}
    assert received[0]['department_context'] == context_id


def test_image_access_rechecks_current_department_permissions(monkeypatch, tmp_path):
    asset_id, entry_id, context_id = uuid4(), uuid4(), uuid4()
    path = tmp_path / 'image.png'
    path.write_bytes(b'test')
    store = SimpleNamespace(asset=lambda _: {'id': asset_id, 'entry_id': entry_id,
                            'storage_path': str(path), 'thumbnail_path': str(path)},
                            get=lambda _: {'status': 'published', 'processing_status': 'ready'})
    monkeypatch.setattr(api.service, 'store', store)
    monkeypatch.setattr(api, 'inside_data', lambda value: path)
    monkeypatch.setattr(departments, 'permitted_for_context', lambda _: {str(entry_id)})
    token = sign_asset_access(str(asset_id), str(entry_id), run_id=str(context_id))
    assert api.asset(asset_id, token).path == path
    monkeypatch.setattr(departments, 'permitted_for_context', lambda _: set())
    with pytest.raises(HTTPException) as error:
        api.asset(asset_id, token)
    assert error.value.status_code == 403


def test_enforced_session_operations_require_department_context(monkeypatch):
    monkeypatch.setattr(departments, 'enforced', lambda: True)
    turn_id = uuid4()
    with pytest.raises(HTTPException) as error:
        session_memory.file_for_turn(session_memory.FileRequest(turn_id=turn_id))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        session_memory.begin(session_memory.Begin(identity=('w', 'b', 'p', 'c', 'u', 'g'),
                                                   host_boot=uuid4(), text='上一份'))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        session_memory.finish(session_memory.Finish(turn_id=turn_id, sources=[]))
    assert error.value.status_code == 403
