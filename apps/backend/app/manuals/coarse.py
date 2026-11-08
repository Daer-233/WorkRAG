"""Cheap score-based coarse ranking for the local manual retrieval pipeline.

No rank fusion or learned model is used. Dense and sparse scores are min-max
normalized separately within this query; keyword scores are divided by their
positive maximum. Missing lanes contribute zero. Equal scores in a nonempty
lane contribute one, so a single result does not lose all its signal.
"""
from dataclasses import dataclass
import math


WEIGHTS = {'dense': 0.45, 'sparse': 0.30, 'keyword': 0.20, 'title_match': 0.05}


@dataclass(frozen=True)
class CoarseCandidate:
    evidence_id: str
    score: float
    features: dict[str, float]


def normalize(scores, *, positive=False):
    values = {eid: float(score) for eid, score in scores.items() if math.isfinite(float(score))}
    if not values:
        return {}
    high, low = max(values.values()), min(values.values())
    if positive:
        return {eid: max(0.0, value) / high if high > 0 else 0.0 for eid, value in values.items()}
    if high == low:
        return {eid: 1.0 for eid in values}
    return {eid: (value - low) / (high - low) for eid, value in values.items()}


def rank_manual_candidates(question, lookup, lanes, limit):
    """Deduplicate by evidence ID, score the union, then retain coarse top-k."""
    ids = set().union(*(set(scores) for scores in lanes.values())) & lookup.keys()
    normalized = {name: normalize(scores, positive=name == 'keyword') for name, scores in lanes.items()}
    query = question.casefold().strip()
    ranked = []
    for eid in ids:
        features = {name: normalized.get(name, {}).get(eid, 0.0) for name in ('dense', 'sparse', 'keyword')}
        title = lookup[eid][0].get('title', '').casefold()
        features['title_match'] = float(bool(query) and query in title)
        score = sum(WEIGHTS[name] * value for name, value in features.items())
        ranked.append(CoarseCandidate(eid, score, features))
    return sorted(ranked, key=lambda row: (-row.score, -row.features['keyword'], row.evidence_id))[:limit]
