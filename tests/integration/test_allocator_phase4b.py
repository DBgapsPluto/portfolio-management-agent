"""Phase 4b BL tilt dial — integration tests."""
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
    scenario: str | None = "goldilocks",
    regime_confidence: float = 0.8,
    force_method: str | None = None,
    n_per_bucket: int = 6,
):
    universe = make_synthetic_universe(n_per_bucket=n_per_bucket)
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
    research_decision = (
        make_research_decision(dominant_scenario=scenario, conviction="high")
        if scenario is not None
        else None
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
        research_decision=research_decision,
        capital_krw=1_000_000_000,
    )
    if force_method is not None:
        state["force_method"] = force_method
    return state


def _get_bl_breakdown(attr):
    """Phase 3b 의 path: optimization.bl_views_breakdown 또는 top-level."""
    opt = attr.get("optimization", {})
    return opt.get("bl_views_breakdown") or attr.get("bl_views_breakdown")


def test_allocator_bl_breakdown_contains_tilt_params(tmp_path, monkeypatch):
    state = _setup_state(tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.8)
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    bl_bd = _get_bl_breakdown(attr)
    assert bl_bd is not None, f"bl_views_breakdown missing, keys: {list(attr.keys())}"
    tp = bl_bd.get("tilt_params")
    assert tp is not None, f"tilt_params missing, bl_bd keys: {list(bl_bd.keys())}"
    assert "tau" in tp
    assert "view_conf_multi" in tp
    assert "view_conf_multi_applied" in tp


def test_allocator_bl_growth_scenario_tau_matches_tilt(tmp_path, monkeypatch):
    state = _setup_state(tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.8)
    result = create_portfolio_allocator()(state)
    bl_bd = _get_bl_breakdown(result["allocation_attribution"])
    tp = bl_bd["tilt_params"]
    assert tp["tau"] == 0.10
    assert tp["view_conf_multi"] == 1.3
    assert tp["view_conf_multi_applied"] is True


def test_allocator_bl_late_cycle_scenario_tau_matches_tilt(tmp_path, monkeypatch):
    """late_cycle: tau=0.05, view_conf_multi=0.8 (all-positive returns, EF feasible)."""
    state = _setup_state(tmp_path, monkeypatch, scenario="late_cycle", regime_confidence=0.8)
    result = create_portfolio_allocator()(state)
    bl_bd = _get_bl_breakdown(result["allocation_attribution"])
    tp = bl_bd["tilt_params"]
    assert tp["tau"] == 0.05
    assert tp["view_conf_multi"] == 0.8
    assert tp["view_conf_multi_applied"] is True


def test_allocator_bl_force_method_no_tilt_applied(tmp_path, monkeypatch):
    """force_method='black_litterman' + 외부 views 없음 → historical fallback,
    bl_views_breakdown 부재 또는 tilt applied=False."""
    state = _setup_state(tmp_path, monkeypatch, scenario=None, regime_confidence=0.5)
    state["force_method"] = "black_litterman"
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    bl_bd = _get_bl_breakdown(attr) or {}
    tp = bl_bd.get("tilt_params", {})
    if tp:
        assert tp.get("view_conf_multi_applied") is False, (
            f"force_method 경로에서 tilt applied=True: {tp}"
        )
