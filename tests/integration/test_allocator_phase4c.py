"""Phase 4c ENB CRITICAL + EW fallback — integration tests."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tests.integration._allocator_state_helpers import (
    make_allocator_state, make_bucket_target, make_factor_panel,
    make_macro_report, make_research_decision, make_risk_report,
    make_synthetic_returns, make_synthetic_universe, make_technical_report,
)
from tradingagents.agents.allocator import portfolio_allocator
from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator


def _setup_state(
    tmp_path,
    monkeypatch,
    *,
    scenario: str = "goldilocks",
    regime_confidence: float = 0.5,
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
    return state


def test_allocator_enb_none_action_default(tmp_path, monkeypatch):
    """ENB >= WARNING (normal): enb_action == 'none'."""
    monkeypatch.setattr(
        portfolio_allocator, "compute_enb",
        lambda *args, **kwargs: 4.0,
    )
    state = _setup_state(tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.5)
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    assert attr.get("enb_action") == "none"
    assert "enb_post_fallback" not in attr


def test_allocator_enb_warning_only_action(tmp_path, monkeypatch):
    """CRITICAL < ENB < WARNING: enb_action == 'warning_only'."""
    monkeypatch.setattr(
        portfolio_allocator, "compute_enb",
        lambda *args, **kwargs: 2.5,
    )
    state = _setup_state(tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.5)
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    assert attr.get("enb_action") == "warning_only"
    assert "enb_post_fallback" not in attr


def test_allocator_enb_critical_ew_fallback(tmp_path, monkeypatch):
    """ENB < CRITICAL (1.5) + n >= 5: EW fallback triggered, enb_post_fallback set."""
    call_count = {"n": 0}
    def fake_enb(*args, **kwargs):
        call_count["n"] += 1
        return 1.5 if call_count["n"] == 1 else 4.5
    monkeypatch.setattr(portfolio_allocator, "compute_enb", fake_enb)
    state = _setup_state(tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.5)
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    assert attr.get("enb_action") == "equal_weight_fallback"
    assert abs(attr.get("enb_post_fallback", 0.0) - 4.5) < 1e-9
    weights = result["weight_vector"].weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    assert all(w <= 0.20 + 1e-6 for w in weights.values())


def test_allocator_enb_critical_action_recorded(tmp_path, monkeypatch):
    """ENB < CRITICAL → enb_action 키가 EW fallback 또는 n_too_small 둘 중 하나."""
    monkeypatch.setattr(
        portfolio_allocator, "compute_enb",
        lambda *args, **kwargs: 1.5,
    )
    state = _setup_state(tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.5)
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    assert attr.get("enb_action") in {
        "equal_weight_fallback", "warning_only_n_too_small",
    }
