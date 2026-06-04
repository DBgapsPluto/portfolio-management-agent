"""Integration — Stage 3 contract path (no manual Phase-2 config keys required)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tradingagents.schemas.portfolio import OptimizationMethod


def _run_allocator(tmp_path, monkeypatch, *, research_decision, config: dict | None = None):
    from tests.integration._allocator_state_helpers import (
        make_allocator_state,
        make_bucket_target,
        make_factor_panel,
        make_macro_report,
        make_risk_report,
        make_synthetic_returns,
        make_synthetic_universe,
        make_technical_report,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=17)
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
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.load_universe",
        lambda _path: universe,
    )

    bt = research_decision.bucket_target
    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=bt,
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=research_decision,
    )
    state["config"] = config or {"allocation_contract_enabled": True}
    return create_portfolio_allocator()(state)


def test_contract_mode_skips_spillover_without_extra_config(tmp_path, monkeypatch):
    """allocation_contract만 있으면 spillover 키를 config에 넣지 않아도 스킵."""
    from tests.integration._allocator_state_helpers import (
        make_research_decision,
        make_research_decision_with_contract,
        make_synthetic_universe,
    )

    universe = make_synthetic_universe(n_per_bucket=4)
    rd = make_research_decision_with_contract(universe)
    result = _run_allocator(tmp_path, monkeypatch, research_decision=rd)
    spill = result["allocation_attribution"]["cash_spillover"]
    assert spill.get("skipped") is True
    assert spill.get("reason") == "bucket_sync_contract"
    assert "bucket_sync_audit" in result["allocation_attribution"]

    # Legacy path (no contract) still runs spillover by default.
    legacy = _run_allocator(
        tmp_path, monkeypatch,
        research_decision=make_research_decision(),
        config={"allocation_contract_enabled": False},
    )
    assert "total_spillover_to_cash" in legacy["allocation_attribution"]["cash_spillover"]


def test_contract_mode_fixed_hrp_and_implementation_alignment(tmp_path, monkeypatch):
    from tests.integration._allocator_state_helpers import (
        make_research_decision_with_contract,
        make_synthetic_universe,
    )

    universe = make_synthetic_universe(n_per_bucket=4)
    rd = make_research_decision_with_contract(universe)
    result = _run_allocator(tmp_path, monkeypatch, research_decision=rd)

    mp = result["allocation_attribution"]["method_picker"]
    assert mp["method"] == OptimizationMethod.HRP.value
    assert mp["rule_fired"] == "contract_fixed_method"

    align = result["allocation_attribution"].get("implementation_alignment")
    assert align is not None
    assert "prior_weights" in align
    assert "feasible_weights" in align
    assert "realized_bucket_weights" in align
    assert "envelope_by_bucket" in align
    assert align["feasible_weights"] == rd.allocation_contract.feasible_weights

    opt = result["allocation_attribution"].get("optimization") or {}
    assert "bucket_envelope_bounds" in opt
