"""D9 — 5/28 E2E dry-run: full pipeline with all external APIs mocked.

Single most important integration test. Confirms the full pipeline, as
configured for the 5/28 DB GAPS submission date, produces the 3-artifact
package compliant with DB GAPS rules.

Mocks applied:
- create_llm_client — all LLM calls (regime/risk/method/bucket/narrative)
- fetch_fred_series_skill — macro_quant_analyst FRED calls
- fetch_ecos_series_skill — macro_quant_analyst ECOS calls
- fetch_volatility_index — market_risk_analyst VIX/VKOSPI
- fetch_credit_spread — market_risk_analyst IG/HY spreads
- fetch_fear_greed_index — market_risk_analyst fear-greed
- compute_market_breadth — market_risk_analyst breadth
- fetch_etf_price_batch — technical_analyst
- fetch_event_calendar_skill — news_analyst
- fetch_macro_news_skill — news_analyst
- fetch_returns_matrix — allocator + fallback
- select_etf_candidates — allocator (AUM filter bypassed for fixture universe)
"""
import csv
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.macro import RegimeClassification
from tradingagents.schemas.news import ImpactAssessment
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet
from tradingagents.schemas.risk import (
    BreadthSnapshot, SpreadSnapshot, SystemicRiskScore, VolatilitySnapshot,
)
from tradingagents.schemas.portfolio import OptimizationMethod
from tradingagents.skills.portfolio.method_picker import MethodChoice


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def universe_path(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
    return universe_json


@pytest.fixture
def fake_returns_df():
    """3-year daily OHLCV for the 5 test-fixture ETFs."""
    rng = np.random.default_rng(42)
    n = 252 * 3
    dates = pd.date_range("2023-05-28", periods=n, freq="B")
    tickers = ["A069500", "A360750", "A411060", "A114260", "A459580"]
    rows = []
    for i, ticker in enumerate(tickers):
        drift = 0.0005 + 0.0001 * i
        vol = 0.012 - 0.002 * i
        close = 100 + np.cumsum(rng.normal(drift, vol, n))
        for d, c in zip(dates, close):
            rows.append({
                "ticker": ticker, "date": d,
                "close": float(c), "open": float(c - 0.5),
                "high": float(c + 1), "low": float(c - 1),
                "volume": 10_000,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Mock LLM helpers
# ---------------------------------------------------------------------------

def _mock_llm_factory(structured_outputs: dict):
    """Build a MagicMock LLM dispatching with_structured_output by schema name."""
    llm = MagicMock()
    llm.invoke.return_value.content = "mocked narrative " * 30

    def structured(schema_class):
        sub = MagicMock()
        sub.invoke.return_value = structured_outputs.get(schema_class.__name__)
        return sub

    llm.with_structured_output = structured
    return llm


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_5_28_dry_run_produces_artifacts(
    tmp_path, universe_path, fake_returns_df, monkeypatch,
):
    """E2E dry-run: all external APIs mocked, 3 artifacts written and validated."""
    artifacts_dir = tmp_path / "artifacts"

    # Pre-build Pydantic instances for every with_structured_output call.
    regime_out = RegimeClassification(
        quadrant="recession_disinflation",
        confidence=0.82,
        drivers=["yield curve inverted 120d", "Sahm rule triggered", "HY OAS widening"],
        reasoning="Curve and labor market signal recession; CPI decelerating.",
    )
    systemic_out = SystemicRiskScore(
        score=6.5, regime="risk_off",
        drivers=["VIX above 22", "HY OAS widening to 5.5%"],
        reasoning="Multiple stress signals.",
    )
    impact_out = ImpactAssessment(
        asset_classes_affected=["us_bond"], direction="up",
        severity=4, reasoning="rate cut expectation",
    )
    method_out = MethodChoice(
        method=OptimizationMethod.HRP, params={},
        reasoning="Recession + risk_off → defensive HRP.",
    )
    # Equal 20% per bucket — HRP with 1 ETF per bucket = 0.20 per ETF, sums to 1.0.
    bucket_out = BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.20,
        bond=0.20, cash_mmf=0.20,
        rationale="Equal bucket split for fixture feasibility",
    )

    deep_llm = _mock_llm_factory({
        "RegimeClassification": regime_out,
        "SystemicRiskScore": systemic_out,
        "MethodChoice": method_out,
        "BucketTarget": bucket_out,
    })
    quick_llm = _mock_llm_factory({
        "ImpactAssessment": impact_out,
    })

    # 1. Mock LLM client factory
    def fake_create_llm_client(provider, model, **kwargs):
        client = MagicMock()
        client.get_llm.return_value = (
            deep_llm if "mini" not in model.lower() else quick_llm
        )
        return client

    monkeypatch.setattr(
        "tradingagents.graph.trading_graph.create_llm_client",
        fake_create_llm_client,
    )

    # 2. Mock FRED — macro_quant_analyst imports fetch_fred_series_skill directly
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

    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_quant_analyst.fetch_fred_series_skill",
        fake_fred_skill,
    )

    # 3. Mock ECOS
    def fake_ecos_skill(name, start, end, **kwargs):
        if "cpi" in name:
            return fake_cpi_monthly
        return fake_ur_monthly

    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_quant_analyst.fetch_ecos_series_skill",
        fake_ecos_skill,
    )

    # 4. Mock volatility (market_risk_analyst)
    fake_vol = VolatilitySnapshot(
        index_name="VIX", current_value=22.5,
        zscore_30d=0.9, percentile_5y=0.72,
        source_date=date(2026, 5, 25),
    )

    def fake_volatility_index(index_name, as_of):
        return fake_vol.model_copy(update={"index_name": index_name})

    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_volatility_index",
        fake_volatility_index,
    )

    # 5. Mock credit spreads
    fake_spread = SpreadSnapshot(
        region="US_IG", current_bps=135.0, percentile_5y=0.65,
        widening=True, source_date=date(2026, 5, 25),
    )

    def fake_credit_spread(region, as_of, api_key=None):
        return fake_spread.model_copy(update={"region": region})

    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_credit_spread",
        fake_credit_spread,
    )

    # 6. Mock fear-greed (allowed to be None — analyst handles it)
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.fetch_fear_greed_index",
        lambda d: None,
    )

    # 7. Mock market breadth
    fake_breadth = BreadthSnapshot(
        market="KOSPI200", advancing_pct=0.45, declining_pct=0.50,
        new_highs_minus_lows=-20, source_date=date(2026, 5, 25),
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.market_risk_analyst.compute_market_breadth",
        lambda market, d: fake_breadth.model_copy(update={"market": market}),
    )

    # 8. Mock ETF price batch (technical_analyst)
    monkeypatch.setattr(
        "tradingagents.agents.analysts.technical_analyst.fetch_etf_price_batch",
        lambda *a, **kw: fake_returns_df,
    )

    # 9. Mock news skills
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_news_analyst.fetch_event_calendar_skill",
        lambda d, days: [],
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_news_analyst.fetch_macro_news_skill",
        lambda **kw: [],
    )

    # 10. Mock returns matrix (allocator + fallback)
    pivot = fake_returns_df.pivot(index="date", columns="ticker", values="close")
    fake_returns_matrix = pivot.pct_change().dropna(how="all")

    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda *a, **kw: fake_returns_matrix,
    )
    monkeypatch.setattr(
        "tradingagents.graph.conditional_logic.fetch_returns_matrix",
        lambda *a, **kw: fake_returns_matrix,
    )

    # 11. Mock select_etf_candidates — bypass AUM filter for fixture universe
    controlled_candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A069500"],
            "global_equity": ["A360750"],
            "fx_commodity": ["A411060"],
            "bond": ["A114260"],
            "cash_mmf": ["A459580"],
        },
        selection_criteria="5/28 fixture-controlled (AUM filter bypassed)",
        total_candidates=5,
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.select_etf_candidates",
        lambda *a, **kw: controlled_candidates,
    )

    # 12. Build config pointing at tmp paths
    from tradingagents.default_config import DEFAULT_CONFIG
    test_config = dict(DEFAULT_CONFIG)
    test_config["preset_dir"] = "presets"
    test_config["universe_path"] = str(universe_path)
    test_config["artifacts_dir"] = str(artifacts_dir)
    test_config["llm_provider"] = "openai"
    test_config["deep_think_llm"] = "gpt-4"
    test_config["quick_think_llm"] = "gpt-4-mini"

    # 13. Run the full pipeline
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    tg = TradingAgentsGraph(preset_name="db_gaps", config=test_config)
    final = tg.run(as_of_date="2026-05-25", capital_krw=1_000_000_000)

    # -----------------------------------------------------------------------
    # Assertions — 5/28 DB GAPS compliance
    # -----------------------------------------------------------------------

    assert final is not None, "Graph returned None"

    # --- A. validation_passed must be set --------------------------------
    assert "validation_passed" in final, (
        f"validation_passed key missing from final state. Keys: {list(final.keys())}"
    )
    # Soft: log but don't crash on validation failure
    if not final["validation_passed"]:
        report = final.get("validation_report")
        hard = (
            [str(v) for v in report.hard_violations]
            if report and hasattr(report, "hard_violations")
            else ["(report unavailable)"]
        )
        pytest.fail(
            f"Validation failed with hard violations: {hard}\n"
            f"This means the mock pipeline produced a non-compliant portfolio."
        )

    # --- B. 3 artifact paths must be populated ---------------------------
    assert "final_portfolio_path" in final, "final_portfolio_path missing"
    assert "philosophy_doc_path" in final, "philosophy_doc_path missing"
    assert "trade_plan_csv_path" in final, "trade_plan_csv_path missing"

    # --- C. portfolio.json -----------------------------------------------
    portfolio_path = Path(final["final_portfolio_path"])
    assert portfolio_path.exists(), f"portfolio.json not written: {portfolio_path}"

    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    assert "weights" in portfolio, "portfolio.json missing 'weights' key"

    weights_total = sum(portfolio["weights"].values())
    assert abs(weights_total - 1.0) < 1e-3, (
        f"Weights sum {weights_total:.6f} != 1.0 (violates DB GAPS mandate)"
    )

    max_weight = max(portfolio["weights"].values(), default=0)
    assert max_weight <= 0.20 + 1e-6, (
        f"Single-ETF 20% cap violated: max weight = {max_weight:.4f}"
    )

    # as_of_date populated
    assert portfolio.get("as_of_date") == "2026-05-25", (
        f"as_of_date mismatch: {portfolio.get('as_of_date')}"
    )

    # capital_krw populated
    assert portfolio.get("capital_krw") == 1_000_000_000, (
        f"capital_krw mismatch: {portfolio.get('capital_krw')}"
    )

    # --- D. philosophy.md ------------------------------------------------
    philosophy_path = Path(final["philosophy_doc_path"])
    assert philosophy_path.exists(), f"philosophy.md not written: {philosophy_path}"
    philosophy_text = philosophy_path.read_text(encoding="utf-8")
    assert len(philosophy_text) > 100, "philosophy.md is suspiciously short"

    # --- E. trade_plan.csv -----------------------------------------------
    trade_plan_path = Path(final["trade_plan_csv_path"])
    assert trade_plan_path.exists(), f"trade_plan.csv not written: {trade_plan_path}"

    with open(trade_plan_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    # Header must start with these 5 mandatory columns
    # (수량(주) added by Plan 4 reports.trade_plan; portfolio_manager v1 has 5)
    assert header[:5] == ["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)"], (
        f"trade_plan.csv header mismatch: {header}"
    )
    assert len(rows) >= 1, "trade_plan.csv has no data rows"

    # Weight column (index 3) must be parseable floats summing to ~1.0
    csv_weight_total = sum(float(r[3]) for r in rows)
    assert abs(csv_weight_total - 1.0) < 1e-3, (
        f"CSV weight sum {csv_weight_total:.6f} != 1.0"
    )

    # --- F. regime captured in portfolio metadata (optional but nice) ----
    assert portfolio.get("method") is not None, "portfolio.json missing 'method'"
