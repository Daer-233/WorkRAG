"""Ranking behavior, rather than merely matching implementation weights."""
from types import SimpleNamespace as NS

from app.manuals.coarse import normalize, rank_manual_candidates
from app.core.config import settings
from test_manual_hybrid import document, engine


def lookup():
    return {eid: ({'id': eid, 'title': '资料'}, 0) for eid in ('a', 'b', 'c')}


def test_raw_sparse_magnitude_cannot_overwhelm_two_other_signals():
    lanes = {'dense': {'a': .95, 'b': .7}, 'sparse': {'b': 10000, 'a': 1},
             'keyword': {'a': 10, 'b': 1}}
    ranked = rank_manual_candidates('问题', lookup(), lanes, 10)
    assert [row.evidence_id for row in ranked] == ['a', 'b']
    scaled = {**lanes, 'sparse': {eid: value * 1000 for eid, value in lanes['sparse'].items()}}
    assert rank_manual_candidates('问题', lookup(), scaled, 10) == ranked


def test_input_order_and_duplicate_lane_membership_do_not_change_ranking():
    lanes = {'dense': {'a': .9, 'b': .8}, 'sparse': {'a': 5, 'c': 1}, 'keyword': {'a': 2}}
    ranked = rank_manual_candidates('问题', lookup(), lanes, 10)
    reordered = {name: dict(reversed(list(scores.items()))) for name, scores in reversed(list(lanes.items()))}
    assert rank_manual_candidates('问题', lookup(), reordered, 10) == ranked
    assert len(ranked) == len({row.evidence_id for row in ranked}) == 3
    assert len(rank_manual_candidates('问题', lookup(), lanes, 2)) == 2


def test_empty_equal_negative_and_nonfinite_scores_are_safe():
    assert normalize({}) == {}
    assert normalize({'a': -3, 'b': -3}) == {'a': 1, 'b': 1}
    assert normalize({'a': 0}, positive=True) == {'a': 0}
    assert normalize({'a': float('nan'), 'b': float('inf')}) == {}
    result = rank_manual_candidates('问题', lookup(), {'dense': {'b': 1, 'a': 1}}, 10)
    assert [row.evidence_id for row in result] == ['a', 'b']
    assert rank_manual_candidates('问题', lookup(), {}, 10) == []


def test_rules_apply_before_bge_and_bge_still_controls_final_order(monkeypatch):
    monkeypatch.setattr(settings, 'retrieval_rerank_candidate_top_k', 3)
    monkeypatch.setattr(settings, 'retrieval_coarse_top_k', 2)
    row = document('one', content='规则粗排测试', count=3)
    retriever, _, calls, _ = engine([row], scores=[1, 9])
    class Provider:
        def search_lane(self, kind, vector, search_filter, limit):
            # Deliberately not returned in score order; ranking must use scores.
            return [NS(id=f'one-s{i}', score=score, payload={
                'manual_entry_id':'one', 'document_version_id':'v-one', 'chunk_level':'child'})
                for i, score in [(2, .1), (1, .5), (0, .9), (0, .8)]]
    retriever.provider_factory = Provider
    result = retriever.search('规则粗排', [row])
    assert len(calls[0][1]) == 2
    assert result.metrics['coarse_input_count'] == 3
    assert result.metrics['coarse_count'] == result.metrics['rerank_input_count'] == 2
    assert [hit.evidence_id for hit in result.hits] == ['one-s1', 'one-s0']
    assert result.hits[0].score == 9


def test_title_match_can_break_an_otherwise_equal_score():
    entries = lookup()
    entries['b'][0]['title'] = '设备借用操作指南'
    rows = rank_manual_candidates('设备借用', entries, {'dense': {'a': 1, 'b': 1}}, 10)
    assert rows[0].evidence_id == 'b'


def test_no_vector_results_still_orders_keyword_candidates_before_rerank(monkeypatch):
    monkeypatch.setattr(settings, 'retrieval_rerank_candidate_top_k', 1)
    row = document('one', title='演示资料')
    row['data']['steps'][0]['instruction'] = '账号申请，填写工号'
    row['data']['steps'][1]['instruction'] = '其他内容'
    retriever, _, calls, _ = engine([row], vector_error=True)
    result = retriever.search('账号申请', [row])
    assert len(calls[0][1]) == 1 and '填写工号' in calls[0][1][0]
    assert result.mode == 'keyword_rerank'
    assert result.metrics['coarse_input_count'] == 1
    assert result.hits[0].evidence_id == 'one-s0'


def test_nonfinite_vector_scores_cannot_enter_coarse_candidates():
    row = document('one', content='匹配内容')
    retriever, _, _, _ = engine([row])
    class Provider:
        def search_lane(self, *args):
            return [NS(id='one-s0', score=float('nan'), payload={
                'manual_entry_id':'one', 'document_version_id':'v-one', 'chunk_level':'child'})]
    retriever.provider_factory = Provider
    result = retriever.search('完全不相干的问题', [row])
    assert result.metrics['dense_count'] == result.metrics['sparse_count'] == 0
    assert result.hits == []
