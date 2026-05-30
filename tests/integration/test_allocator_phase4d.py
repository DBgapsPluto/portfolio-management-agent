"""Phase 4d QIS nonlinear shrinkage — integration tests."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tests.integration._allocator_state_helpers import (
    make_allocator_state, make_bucket_target, make_factor_panel,
    make_macro_report, make_research_decision, make_risk_report,
    make_synthetic_returns, make_synthetic_universe, make_technical_report,
)
from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator


def _setup_state(
    tmp_path,
    monkeypatch,
    *,
    scenario: str = "goldilocks",
    regime_confidence: float = 0.5,
    force_method: str | None = None,
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
            dominant_scenario=scenario,
            conviction="high",
        ),
        capital_krw=1_000_000_000,
    )
    if force_method is not None:
        state["force_method"] = force_method
    return state


def test_allocator_cov_estimator_default_is_qis(tmp_path, monkeypatch):
    state = _setup_state(tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.5)
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    bd = attr.get("cov_breakdown") or attr.get("optimization", {}).get("cov_breakdown")
    assert bd is not None, f"cov_breakdown missing, keys: {list(attr.keys())}"
    assert bd["estimator"] == "qis"


def test_allocator_nco_cov_breakdown_estimator_qis(tmp_path, monkeypatch):
    state = _setup_state(
        tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.5,
        force_method="nco",
    )
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    opt = attr.get("optimization", {})
    nco_per_pool = opt.get("nco_breakdown_per_pool", {})
    assert nco_per_pool, "nco_breakdown_per_pool empty"
    qis_pools = [
        p for p, data in nco_per_pool.items()
        if data.get("cov_breakdown", {}).get("estimator") == "qis"
    ]
    assert qis_pools, f"no pool has estimator='qis': {nco_per_pool}"
