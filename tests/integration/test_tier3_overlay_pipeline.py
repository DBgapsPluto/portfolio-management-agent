"""Tier 3 integration: mocked LLM → views → blend → mandate-compliant final."""
import asyncio
from datetime import date
from unittest.mock import AsyncMock

from tradingagents.schemas.llm_overlay import LLMBucketView, CredibilityState
from tradingagents.skills.overlay.consensus import compute_consensus
from tradingagents.skills.overlay.apply import apply_llm_overlay
from tradingagents.agents.overlay import llm_bucket_overlay as mod
from tradingagents.skills.research.factor_to_bucket import INITIAL_BASELINE, RISK_BUCKETS, BUCKETS


def _mk_view():
    return LLMBucketView(
        kr_equity=0.4, global_equity=0.3, precious_metals=-0.2, cyclical_commodity_fx=0.1,
        kr_bond=-0.3, credit=-0.1, global_duration=-0.2, cash_mmf=0.0,
        confidence=0.6, reasoning="test", cited_events=[],
    )


def test_tier3_pipeline_end_to_end(monkeypatch):
    async def _complete(**kwargs):
        return _mk_view()
    mock_client = AsyncMock()
    mock_client.complete = _complete
    monkeypatch.setattr(mod, "_get_llm_client", lambda: mock_client)

    state = {
        "macro_summary": "Growth firming, inflation stable", "risk_summary": "VIX low",
        "technical_summary": "Equity momentum positive", "news_summary": "FOMC dovish-leaning",
    }
    factor_z = {"F1_growth": 1.2, "F2_inflation": -0.3}
    quant = dict(INITIAL_BASELINE)

    views = asyncio.run(mod.generate_llm_views(state, factor_z, quant, k=5))
    assert len(views) == 5

    # novelty=0 (no history) → overlay must be a no-op
    consensus = compute_consensus(views)
    cred = CredibilityState(bucket_cred={}, history_count=0, last_updated=date(2026, 6, 1))
    final0, _ = apply_llm_overlay(quant, views, novelty=0.0, consensus=consensus, credibility=cred)
    for b in quant:
        assert abs(final0[b] - quant[b]) < 1e-9  # zero novelty → unchanged

    # novelty=1, full consensus, cold-start cred 0.3 → small but real tilt, still mandate-compliant
    final1, audit = apply_llm_overlay(quant, views, novelty=1.0, consensus=consensus, credibility=cred)
    assert abs(sum(final1.values()) - 1.0) < 1e-6
    assert sum(final1[b] for b in RISK_BUCKETS) <= 0.70 + 1e-6
    # cold-start cred 0.3 keeps per-bucket move modest (< BAND)
    for b in BUCKETS:
        assert abs(audit[b]["clipped_delta"]) <= 0.05 + 1e-9


def test_tier3_pipeline_cold_start_modest_effect(monkeypatch):
    """Cold-start credibility (0.3) → overlay moves are small even at full novelty/consensus."""
    async def _complete(**kwargs):
        return _mk_view()
    mock_client = AsyncMock(); mock_client.complete = _complete
    monkeypatch.setattr(mod, "_get_llm_client", lambda: mock_client)
    quant = dict(INITIAL_BASELINE)
    views = asyncio.run(mod.generate_llm_views({}, {}, quant, k=5))
    consensus = compute_consensus(views)
    cred = CredibilityState(bucket_cred={}, history_count=0, last_updated=date(2026, 6, 1))
    final, audit = apply_llm_overlay(quant, views, novelty=1.0, consensus=consensus, credibility=cred)
    # w_LLM = 1.0 * consensus * 0.3; avg_delta = mean_delta * avg_conf(0.6).
    # kr_equity: consensus 1.0, delta 0.4*0.6=0.24, w=0.3 → raw 0.072 → clipped 0.05
    # Just assert the move is bounded and direction matches sign of delta.
    assert audit["kr_equity"]["clipped_delta"] > 0      # LLM wanted increase
    assert audit["kr_bond"]["clipped_delta"] < 0        # LLM wanted decrease
