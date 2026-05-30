"""Phase 2b integration — adaptive N + ENB greedy 통합 검증."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tests.integration._allocator_state_helpers import (
    BUCKET_CATEGORIES, make_allocator_state, make_bucket_target,
    make_factor_panel, make_macro_report, make_research_decision,
    make_risk_report, make_synthetic_returns, make_synthetic_universe,
    make_technical_report,
)
from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator,
)


def _setup_state(tmp_path, monkeypatch, *, capital_krw: float = 1_000_000_000,
                 n_per_bucket: int = 6, bt=None):
    universe = make_synthetic_universe(n_per_bucket=n_per_bucket)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())
    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=5)
    factor_panel = make_factor_panel(tickers)
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )
    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=bt or make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
        capital_krw=capital_krw,
    )
    return state


def test_adaptive_n_max_small_bucket_uses_capacity_cap(tmp_path, monkeypatch):
    """1B × kr_equity 0.10 = 100M → n_max = 2."""
    bt = make_bucket_target(
        kr_equity=0.10, global_equity=0.20, fx_commodity=0.10,
        bond=0.30, cash_mmf=0.30,
    )
    state = _setup_state(tmp_path, monkeypatch, bt=bt, n_per_bucket=10)
    result = create_portfolio_allocator()(state)
    bucket_attr = result["allocation_attribution"]["buckets"]["kr_equity"]
    trace = bucket_attr["selection_trace"]
    assert trace["n_max_components"]["capital_cap"] == 2
    # n_max_chosen 이 모든 cap 의 min 일 수 있음
    n_chosen = len(bucket_attr["chosen"])
    assert n_chosen <= 2


def test_adaptive_n_max_large_bucket_uses_abs_max(tmp_path, monkeypatch):
    """대형 자본 + 큰 bucket → abs_max 8 도달."""
    bt = make_bucket_target(
        kr_equity=0.50, global_equity=0.20, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.30,
    )
    state = _setup_state(
        tmp_path, monkeypatch, bt=bt, n_per_bucket=15,
        capital_krw=10_000_000_000_000,  # 10T → capital_cap 매우 큼
    )
    result = create_portfolio_allocator()(state)
    bucket_attr = result["allocation_attribution"]["buckets"]["kr_equity"]
    trace = bucket_attr["selection_trace"]
    # abs_max 가 가장 작은 cap 이 됨
    assert trace["n_max_components"]["abs_max"] == 8


def test_enb_greedy_attribution_has_progression(tmp_path, monkeypatch):
    """selection_trace 의 progression / stop_reason 채워짐."""
    state = _setup_state(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    for bucket_name in ("kr_equity", "global_equity", "bond"):
        bucket_attr = result["allocation_attribution"]["buckets"][bucket_name]
        trace = bucket_attr["selection_trace"]
        assert "enb_progression" in trace
        assert "stop_reason" in trace
        assert trace["stop_reason"] in {
            "n_max_reached", "delta_below_threshold",
            "pool_exhausted", "no_positive_alpha", "capacity_zero",
        }


def test_attribution_selection_strategy_enb_greedy(tmp_path, monkeypatch):
    """attribution.config.selection_strategy = 'enb_greedy'."""
    state = _setup_state(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    config = result["allocation_attribution"]["config"]
    assert config.get("selection_strategy") == "enb_greedy"
    assert "capital_krw" in config
