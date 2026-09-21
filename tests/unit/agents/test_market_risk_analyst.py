from datetime import date
from unittest.mock import MagicMock

import pandas as pd

from tradingagents.agents.analysts.market_risk_analyst import create_market_risk_analyst
from tradingagents.schemas.reports import RiskReport
from tradingagents.schemas.risk import (
    VolatilitySnapshot, SpreadSnapshot, BreadthSnapshot, SystemicRiskScore,
    PCASnapshot,
)


def test_risk_analyst_orchestration(monkeypatch):
    quick_llm = MagicMock()
    deep_llm = MagicMock()

    systemic_out = SystemicRiskScore(
        score=6.5, regime="risk_off",
        drivers=["VIX spike"], reasoning="x",
        source_date=date(2026, 5, 10),
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = systemic_out

    fake_vol = VolatilitySnapshot(
        index_name="VIX", current_value=18.5,
        zscore_30d=0.4, percentile_5y=0.55, source_date=date(2026, 5, 10),
    )
    fake_spread = SpreadSnapshot(
        region="US_IG", current_bps=120.0, percentile_5y=0.6,
        widening=False, source_date=date(2026, 5, 10),
    )
    fake_breadth = BreadthSnapshot(
        market="KOSPI200", advancing_pct=0.55, declining_pct=0.40,
        new_highs_minus_lows=0, source_date=date(2026, 5, 10),
    )
    fake_pca = PCASnapshot(
        first_eigenvalue_share=0.65,
        n_assets_analyzed=4,
        is_concentrated=True,
        source_date=date(2026, 5, 10),
    )

    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_volatility_index",
        lambda name, d: fake_vol if name == "VIX" else fake_vol.model_copy(update={"index_name": "VKOSPI"}),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_credit_spread",
        lambda region, d: fake_spread.model_copy(update={"region": region}),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_fear_greed_index",
        lambda d: None,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.compute_market_breadth",
        lambda market, d: fake_breadth.model_copy(update={"market": market}),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.compute_correlation_concentration",
        lambda df, d: fake_pca,
    )

    quick_llm.invoke.return_value.content = "risk narrative"

    node = create_market_risk_analyst(quick_llm, deep_llm)
    state = {"as_of_date": "2026-05-10"}
    result = node(state)
    assert "risk_report" in result
    assert isinstance(result["risk_report"], RiskReport)
    assert result["risk_report"].systemic_score.regime == "risk_off"
    # fear_greed=None → fallback SentimentSnapshot
    assert result["risk_report"].fear_greed.staleness_days == 99
    assert "risk_summary" in result
    assert len(result["risk_summary"]) <= 2000


def test_risk_analyst_renders_vix_vkospi_sentinel_as_na(monkeypatch):
    """B5: when VIX/VKOSPI fetch fails (sentinel: current_value=0.0,
    staleness_days=99), the analyst must render 'n/a' — NOT a misleading 0.0 the
    LLM reads as extreme calm — both into the systemic-score prompt and the
    human-facing summary, and count them in the sentinel inventory."""
    P = "tradingagents.agents.analysts.market_risk_analyst."
    quick_llm = MagicMock()
    deep_llm = MagicMock()

    sentinel_vol = VolatilitySnapshot(
        index_name="VIX", current_value=0.0, zscore_30d=0.0, percentile_5y=0.5,
        source_date=date(2026, 5, 10), staleness_days=99,
    )
    fake_spread = SpreadSnapshot(
        region="US_IG", current_bps=120.0, percentile_5y=0.6,
        widening=False, source_date=date(2026, 5, 10),
    )
    fake_breadth = BreadthSnapshot(
        market="KOSPI200", advancing_pct=0.55, declining_pct=0.40,
        new_highs_minus_lows=0, source_date=date(2026, 5, 10),
    )
    fake_pca = PCASnapshot(
        first_eigenvalue_share=0.65, n_assets_analyzed=4,
        is_concentrated=True, source_date=date(2026, 5, 10),
    )
    monkeypatch.setattr(P + "fetch_volatility_index",
                        lambda name, d: sentinel_vol.model_copy(update={"index_name": name}))
    monkeypatch.setattr(P + "fetch_credit_spread",
                        lambda region, d: fake_spread.model_copy(update={"region": region}))
    monkeypatch.setattr(P + "fetch_fear_greed_index", lambda d: None)
    monkeypatch.setattr(P + "compute_market_breadth",
                        lambda market, d: fake_breadth.model_copy(update={"market": market}))
    monkeypatch.setattr(P + "compute_correlation_concentration", lambda df, d: fake_pca)

    captured: dict = {}

    def fake_score(*a, **kw):
        captured.update(kw)
        return SystemicRiskScore(
            score=5.0, regime="neutral", drivers=["data degraded"], reasoning="x",
            source_date=date(2026, 5, 10),
        )
    monkeypatch.setattr(P + "score_systemic_risk", fake_score)
    quick_llm.invoke.return_value.content = "risk narrative"

    result = create_market_risk_analyst(quick_llm, deep_llm)({"as_of_date": "2026-05-10"})

    # (1) LLM input: ALL sentinel VIX/VKOSPI fields passed as 'n/a', never 0.0
    assert captured["vix"] == "n/a" and captured["vkospi"] == "n/a"
    assert captured["vix_z"] == "n/a" and captured["vix_pct"] == "n/a"
    assert captured["vix_change_4w"] == "n/a" and captured["vkospi_change_4w"] == "n/a"
    # (2) human-facing summary renders n/a, not a calm-looking 0.0
    summ = result["risk_summary"]
    assert "VIX: n/a" in summ and "VKOSPI: n/a" in summ
    assert "VIX: 0.0" not in summ and "VKOSPI: 0.0" not in summ
    # (3) sentinel inventory now tracks the primary vol inputs
    assert "Sentinels:" in summ and "vix" in summ


def test_risk_prompt_vol_fields_have_no_format_spec():
    # B5 contract: VIX/VKOSPI sentinels are passed to score_systemic_risk as the
    # STRING 'n/a'. If prompts/risk-analysis.md ever added a numeric format spec
    # (e.g. {vix:.1f}) the str.format() render would crash on 'n/a' in production.
    # Lock the bare-placeholder contract so a future prompt edit can't break it.
    import re
    from pathlib import Path
    prompt = Path("prompts/risk-analysis.md").read_text(encoding="utf-8")
    for field in ["vix", "vix_z", "vix_pct", "vix_change_4w", "vkospi", "vkospi_change_4w"]:
        for m in re.finditer(r"\{" + re.escape(field) + r"([:}])", prompt):
            assert m.group(1) == "}", f"{{{field}}} must have no format spec (would crash on 'n/a')"
