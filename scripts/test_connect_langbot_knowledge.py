import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name('connect-langbot-knowledge.py')
spec = importlib.util.spec_from_file_location('connect_langbot_knowledge', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def client_with_results(results):
    class Client:
        def post(self, url, json):
            assert url == f'/api/v1/knowledge/bases/{module.KB}/retrieve'
            return {'results': results}
    return Client()


def test_verify_rejects_empty_langbot_result(monkeypatch):
    monkeypatch.setattr(module, 'data', lambda response: response)
    with pytest.raises(RuntimeError, match='no usable evidence'):
        module.verify(client_with_results([]))


def test_verify_rejects_metadata_only_or_text_only(monkeypatch):
    monkeypatch.setattr(module, 'data', lambda response: response)
    with pytest.raises(RuntimeError):
        module.verify(client_with_results([{'content': '', 'metadata': {'entry_id': 'x'}}]))
    with pytest.raises(RuntimeError):
        module.verify(client_with_results([{'content': '正文', 'metadata': {}}]))


def test_verify_accepts_text_and_metadata(monkeypatch):
    monkeypatch.setattr(module, 'data', lambda response: response)
    result = module.verify(client_with_results([{'content': '正文', 'metadata': {'entry_id': 'x'}}]), 'VPN')
    assert result == {'matched_results': 1, 'has_text': True, 'has_metadata': True}
