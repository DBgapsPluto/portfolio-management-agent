import pytest
from datetime import date
from tradingagents.schemas.llm_overlay import LLMBucketView, CredibilityState
from tradingagents.skills.overlay.apply import apply_llm_overlay, BAND
from tradingagents.skills.research.factor_to_bucket import INITIAL_BASELINE, RISK_BUCKETS, BUCKETS


def _make_view(**deltas):
    defaults = {b: 0.0 for b in BUCKETS}
    defaults.update(deltas)
    return LLMBucketView(**defaults, confidence=0.5, reasoning="", cited_events=[])


def _cred(val=1.0):
    return CredibilityState(bucket_cred={b: val for b in BUCKETS}, history_count=0,
                            last_updated=date(2026, 6, 1))


def test_apply_overlay_respects_band():
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=1.0)] * 5
    consensus = {b: 1.0 for b in BUCKETS}
    final, audit = apply_llm_overlay(quant, views, novelty=1.0, consensus=consensus, credibility=_cred())
    assert audit["kr_equity"]["clipped_delta"] <= BAND + 1e-9
    assert audit["kr_equity"]["clipped_delta"] > 0


def test_apply_overlay_mandate_compliance():
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=0.8, global_equity=0.8, precious_metals=0.8,
                        cyclical_commodity_fx=0.8)] * 5
    consensus = {b: 1.0 for b in BUCKETS}
    final, _ = apply_llm_overlay(quant, views, novelty=1.0, consensus=consensus, credibility=_cred())
    assert abs(sum(final.values()) - 1.0) < 1e-6
    assert sum(final[b] for b in RISK_BUCKETS) <= 0.70 + 1e-6


def test_apply_overlay_zero_novelty_unchanged():
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=0.5)] * 5
    final, _ = apply_llm_overlay(quant, views, novelty=0.0,
                                 consensus={b: 1.0 for b in BUCKETS}, credibility=_cred())
    for b in quant:
        assert abs(final[b] - quant[b]) < 1e-9


def test_apply_overlay_zero_consensus_unchanged():
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=0.5)] * 5
    final, _ = apply_llm_overlay(quant, views, novelty=1.0,
                                 consensus={b: 0.0 for b in BUCKETS}, credibility=_cred())
    for b in quant:
        assert abs(final[b] - quant[b]) < 1e-9


def test_apply_overlay_band_param_override():
    """Smaller band → smaller max delta."""
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=1.0)] * 5
    consensus = {b: 1.0 for b in BUCKETS}
    final, audit = apply_llm_overlay(quant, views, novelty=1.0, consensus=consensus,
                                     credibility=_cred(), band=0.02)
    assert audit["kr_equity"]["clipped_delta"] <= 0.02 + 1e-9


def test_apply_overlay_negative_direction():
    """LLM says decrease kr_equity → final kr_equity < quant (before re-projection effects)."""
    quant = dict(INITIAL_BASELINE)
    views = [_make_view(kr_equity=-1.0)] * 5
    consensus = {b: 1.0 for b in BUCKETS}
    final, audit = apply_llm_overlay(quant, views, novelty=1.0, consensus=consensus, credibility=_cred())
    assert audit["kr_equity"]["clipped_delta"] < 0
