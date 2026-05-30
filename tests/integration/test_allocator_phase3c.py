"""Phase 3c NCO backbone cutover — integration tests."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tests.integration._allocator_state_helpers import (
    make_allocator_state, make_bucket_target, make_factor_panel,
    make_macro_report, make_research_decision, make_risk_report,
    make_synthetic_returns, make_synthetic_universe, make_technical_report,
)
from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator,
)


def _setup_state_phase3c(
    tmp_path,
    monkeypatch,
    *,
    scenario: str | None = None,
    regime_confidence: float = 0.5,
    conviction: str = "high",
):
    universe = make_synthetic_universe(n_per_bucket=6)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())
    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=42)
    factor_panel = make_factor_panel(tickers)
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[
            [t for t in eligible if t in returns.columns]
        ],
    )
    state = make_allocator_state(
        as_of=date(2026, 5, 30),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(
            regime_quadrant="growth_disinflation",
            regime_confidence=regime_confidence,
        ),
        risk_report=make_risk_report(systemic_score=5.0, systemic_regime="neutral"),
        research_decision=make_research_decision(
            dominant_scenario=scenario or "goldilocks",
            conviction=conviction,
        ),
        capital_krw=1_000_000_000,
    )
    # scenario=None 의 경우 research_decision 을 제거해 picker 가 default rule 경유
    if scenario is None:
        state["research_decision"] = None
    return state


def test_allocator_default_method_is_nco_when_no_scenario(tmp_path, monkeypatch):
    """scenario 없고 regime_confidence 낮을 때 → default rule → NCO."""
    state = _setup_state_phase3c(
        tmp_path, monkeypatch, scenario=None, regime_confidence=0.5,
    )
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] == "nco"
    assert mp["rule_fired"] == "default"


def test_allocator_overheating_scenario_uses_nco(tmp_path, monkeypatch):
    """overheating scenario + low confidence → scenario_mapping rule → NCO."""
    state = _setup_state_phase3c(
        tmp_path, monkeypatch, scenario="overheating", regime_confidence=0.5,
    )
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] == "nco"
    assert mp["rule_fired"] == "scenario_mapping"


def test_allocator_low_conviction_no_downgrade(tmp_path, monkeypatch):
    """overheating + low conviction → NCO (no HRP downgrade)."""
    state = _setup_state_phase3c(
        tmp_path, monkeypatch, scenario="overheating", regime_confidence=0.5,
        conviction="low",
    )
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] == "nco"
    assert mp["rule_fired"] == "scenario_mapping"
    assert "downgraded_from_hrp" not in mp.get("inputs", {})
