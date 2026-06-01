from tradingagents.schemas.llm_overlay import LLMBucketView
from tradingagents.skills.overlay.consensus import compute_consensus


def _make_view(**deltas):
    defaults = {b: 0.0 for b in [
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    ]}
    defaults.update(deltas)
    return LLMBucketView(**defaults, confidence=0.5, reasoning="", cited_events=[])


def test_unanimous_consensus_is_1():
    views = [_make_view(kr_equity=0.5) for _ in range(5)]
    assert compute_consensus(views)["kr_equity"] == 1.0


def test_split_consensus():
    views = [_make_view(kr_equity=0.5)] * 3 + [_make_view(kr_equity=-0.5)] * 2
    assert abs(compute_consensus(views)["kr_equity"] - 0.2) < 1e-9


def test_all_neutral():
    views = [_make_view(kr_equity=0.0)] * 5
    assert compute_consensus(views)["kr_equity"] == 0.0


def test_below_threshold_treated_neutral():
    # delta 0.05 < NEUTRAL_THRESHOLD 0.1 → counts as 0
    views = [_make_view(kr_equity=0.05)] * 5
    assert compute_consensus(views)["kr_equity"] == 0.0


def test_empty_views_all_zero():
    c = compute_consensus([])
    assert all(v == 0.0 for v in c.values())
    assert len(c) == 8
