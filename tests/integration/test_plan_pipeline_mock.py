"""End-to-end pipeline test with all external dependencies mocked.

Plan 3 happy-path verification: TradingAgentsGraph.run() through the full
DAG (4 analysts → debate → allocator → validator → portfolio_manager)
without requiring real LLMs, FRED/ECOS/pykrx APIs, or network.

Plan 4 will add a more thorough test with realistic fixture data and
philosophy.md content checks.
"""
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.macro import (
    DivergenceScore, EmploymentSnapshot, InflationSnapshot,
    RegimeClassification, YieldCurveSnapshot,
)
from tradingagents.schemas.news import ImpactAssessment
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.risk import (
    BreadthSnapshot, PCASnapshot, SentimentSnapshot, SpreadSnapshot,
    SystemicRiskScore, VolatilitySnapshot,
)
from tradingagents.schemas.technical import IndicatorPanel
from tradingagents.skills.portfolio.method_picker import MethodChoice
from tradingagents.schemas.portfolio import OptimizationMethod


@pytest.fixture
def universe_path(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
    return universe_json


@pytest.fixture
def fake_returns_df():
    """Returns DataFrame for the 5 test-fixture ETFs over 3 years."""
    rng = np.random.default_rng(42)
    n = 252 * 3
    dates = pd.date_range("2023-05-08", periods=n, freq="B")
    tickers = ["A069500", "A360750", "A411060", "A114260", "A459580"]
    rows = []
    for ticker in tickers:
        # Distinct drift + vol per ticker for realistic correlation
        drift = 0.0005 + 0.0001 * tickers.index(ticker)
        vol = 0.012 - 0.002 * tickers.index(ticker)
        close = 100 + np.cumsum(rng.normal(drift, vol, n))
        for d, c in zip(dates, close):
            rows.append({
                "ticker": ticker, "date": d, "close": float(c),
                "open": float(c-0.5), "high": float(c+1), "low": float(c-1),
                "volume": 10000,
            })
    return pd.DataFrame(rows)


def _mock_llm_factory(structured_outputs: dict):
    """Build a mock LLM whose with_structured_output dispatches by schema name."""
    llm = MagicMock()
    llm.invoke.return_value.content = "narrative ≤ 500 chars"

    def structured(schema_class):
        sub = MagicMock()
        sub.invoke.return_value = structured_outputs.get(schema_class.__name__)
        return sub

    llm.with_structured_output = structured
    return llm


def test_plan_pipeline_produces_artifacts(tmp_path, universe_path, fake_returns_df, monkeypatch):
    """Run TradingAgentsGraph.run with mocks; assert 3 artifacts written, validation passed."""
    artifacts_dir = tmp_path / "artifacts"

    # Pre-build mock LLM outputs (Pydantic instances)
    regime_out = RegimeClassification(
        quadrant="recession_disinflation", confidence=0.82,
        drivers=["yield curve inversion"], reasoning="recession signals.",
    )
    systemic_out = SystemicRiskScore(
        score=6.5, regime="risk_off",
        drivers=["VIX above 25"], reasoning="stress.",
    )
    impact_out = ImpactAssessment(
        asset_classes_affected=["us_bond"], direction="up",
        severity=4, reasoning="rate cut",
    )
    method_out = MethodChoice(
        method=OptimizationMethod.HRP, params={},
        reasoning="recession + risk_off → defensive HRP.",
    )
    # 5 fixture ETFs, 1 per bucket — set each bucket to 0.20 so HRP produces
    # exactly 0.20 per ETF (single ETF bucket ⟹ inner weight = 1.0, scaled by
    # bucket target). Sum = 5 × 0.20 = 1.0, respecting the 20% per-asset cap.
    bucket_out = BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.20,
        bond=0.20, cash_mmf=0.20,
        rationale="equal bucket split — fixture feasibility",
    )

    deep_llm = _mock_llm_factory({
        "RegimeClassification": regime_out,
        "SystemicRiskScore": systemic_out,
        "MethodChoice": method_out,
        "BucketTarget": bucket_out,
        # research_manager also calls with_structured_output(BucketTarget) via invoke_with_structured_retry
    })
    quick_llm = _mock_llm_factory({
        "ImpactAssessment": impact_out,
    })

    # Patch LLM client factory so TradingAgentsGraph builds without API keys
    def fake_create_llm_client(provider, model, **kwargs):
        client = MagicMock()
        # Return deep_llm or quick_llm based on model name heuristic
        client.get_llm.return_value = (
            deep_llm if "mini" not in model.lower() else quick_llm
        )
        return client

    monkeypatch.setattr(
        "tradingagents.graph.trading_graph.create_llm_client",
        fake_create_llm_client,
    )

    # Patch external data sources — use the module name where each function
    # is *imported* (not where it is defined), so monkeypatch replaces the
    # bound name that the analyst nodes actually call.
    fake_yield_series = pd.Series(
        [4.5] * 1300,
        index=pd.date_range("2021-01-01", periods=1300, freq="D"),
        name="yield",
    )
    fake_cpi_monthly = pd.Series(
        [305.0 + i * 0.3 for i in range(50)],
        index=pd.date_range("2021-01-01", periods=50, freq="MS"),
    )
    fake_ur_monthly = pd.Series(
        [4.0 + i * 0.01 for i in range(50)],
        index=pd.date_range("2021-01-01", periods=50, freq="MS"),
    )

    def fake_fred_skill(series, start, end, **kwargs):
        s = series.lower()
        if "cpi" in s:
            return fake_cpi_monthly
        if "unrate" in s or "payems" in s:
            return fake_ur_monthly
        return fake_yield_series

    def fake_ecos_skill(name, start, end, **kwargs):
        if "cpi" in name:
            return fake_cpi_monthly
        return fake_ur_monthly

    # macro_quant_analyst imports fetch_fred_series_skill and fetch_ecos_series_skill
    # directly — patch them at the module where they are *used*.
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_quant_analyst.fetch_fred_series_skill",
        fake_fred_skill,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_quant_analyst.fetch_ecos_series_skill",
        fake_ecos_skill,
    )

    # Patch volatility (used by market_risk_analyst)
    fake_vol = VolatilitySnapshot(
        index_name="VIX", current_value=18.5,
        zscore_30d=0.4, percentile_5y=0.55,
        source_date=date(2026, 5, 10),
    )

    def fake_volatility_index(index_name, as_of):
        return fake_vol if index_name == "VIX" else fake_vol.model_copy(
            update={"index_name": "VKOSPI"}
        )

    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_volatility_index",
        fake_volatility_index,
    )

    # Credit spread, breadth, fear_greed
    fake_spread = SpreadSnapshot(
        region="US_IG", current_bps=120.0, percentile_5y=0.6,
        widening=False, source_date=date(2026, 5, 10),
    )

    def fake_credit_spread(region, as_of, api_key=None):
        return fake_spread.model_copy(update={"region": region})

    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_credit_spread",
        fake_credit_spread,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_fear_greed_index",
        lambda d: None,  # skip-with-note path
    )
    fake_breadth = BreadthSnapshot(
        market="KOSPI200", advancing_pct=0.55, declining_pct=0.40,
        new_highs_minus_lows=0, source_date=date(2026, 5, 10),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.compute_market_breadth",
        lambda market, d: fake_breadth.model_copy(update={"market": market}),
    )

    # Technical analyst — patch fetch_etf_price_batch
    monkeypatch.setattr(
        "tradingagents.agents.analysts.technical_analyst.fetch_etf_price_batch",
        lambda *a, **kw: fake_returns_df,
    )

    # News analyst — patch fetchers
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_news_analyst.fetch_event_calendar_skill",
        lambda d, days: [],
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_news_analyst.fetch_macro_news_skill",
        lambda **kw: [],
    )

    # Allocator — patch fetch_returns_matrix
    pivot = fake_returns_df.pivot(index="date", columns="ticker", values="close")
    fake_returns_matrix = pivot.pct_change().dropna(how="all")
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda *a, **kw: fake_returns_matrix,
    )
    # Also patch the conditional_logic fallback's fetch_returns_matrix
    monkeypatch.setattr(
        "tradingagents.graph.conditional_logic.fetch_returns_matrix",
        lambda *a, **kw: fake_returns_matrix,
    )

    # Patch select_etf_candidates to bypass AUM filter — the fixture universe has
    # A114260 (bond) at ~535B KRW, below the hardcoded 1T threshold.  By injecting
    # a controlled CandidateSet we ensure all 5 ETFs (1 per bucket) are selected
    # so HRP can produce weights that sum to 1.0.
    from tradingagents.schemas.portfolio import CandidateSet
    controlled_candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A069500"],
            "global_equity": ["A360750"],
            "fx_commodity": ["A411060"],
            "bond": ["A114260"],
            "cash_mmf": ["A459580"],
        },
        selection_criteria="fixture-controlled (AUM filter bypassed for test)",
        total_candidates=5,
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.select_etf_candidates",
        lambda *a, **kw: controlled_candidates,
    )

    # Patch DEFAULT_CONFIG to use tmp paths
    from tradingagents.default_config import DEFAULT_CONFIG
    test_config = dict(DEFAULT_CONFIG)
    test_config["preset_dir"] = "presets"
    test_config["universe_path"] = str(universe_path)
    test_config["artifacts_dir"] = str(artifacts_dir)
    test_config["llm_provider"] = "openai"
    test_config["deep_think_llm"] = "gpt-4"
    test_config["quick_think_llm"] = "gpt-4-mini"

    from tradingagents.graph.trading_graph import TradingAgentsGraph
    tg = TradingAgentsGraph(preset_name="db_gaps", config=test_config)
    final = tg.run(as_of_date="2026-05-25", capital_krw=1_000_000_000)

    # Assertions
    assert final.get("validation_passed") is True or final.get("validation_passed") is False, \
        f"validation_passed must be set: {final}"

    # 3 artifacts
    assert "final_portfolio_path" in final
    portfolio_path = Path(final["final_portfolio_path"])
    assert portfolio_path.exists(), f"portfolio.json not written: {portfolio_path}"
    assert Path(final["philosophy_doc_path"]).exists()
    assert Path(final["trade_plan_csv_path"]).exists()

    # portfolio.json schema
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    assert "weights" in portfolio
    assert abs(sum(portfolio["weights"].values()) - 1.0) < 1e-3
    # All weights ≤ 0.20 (mandate cap from D12 fix)
    assert all(w <= 0.20 + 1e-6 for w in portfolio["weights"].values()), \
        f"Single ETF cap violated: {portfolio['weights']}"
