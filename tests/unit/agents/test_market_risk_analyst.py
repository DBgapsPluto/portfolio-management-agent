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
