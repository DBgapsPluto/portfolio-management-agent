"""Stage 2 (research_manager) → Stage 3 (allocator) contract pipeline."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tradingagents.schemas.portfolio import OptimizationMethod


def _patch_io(monkeypatch, universe, returns):
    monkeypatch.setattr(
        "tradingagents.agents.managers.research_manager.load_universe",
        lambda _path: universe,
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.load_universe",
        lambda _path: universe,
    )
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


def test_stage2_builds_contract_stage3_consumes_it(tmp_path, monkeypatch):
    from tests.integration._allocator_state_helpers import (
        make_factor_panel,
        make_macro_report,
        make_risk_report,
        make_synthetic_returns,
        make_synthetic_universe,
        make_technical_report,
        patch_contract_alpha_probe,
    )
    from tests.unit.agents.test_research_manager_factor_model import _full_state
    from tradingagents.agents.allocator.portfolio_allocator import (
        create_portfolio_allocator,
    )
    from tradingagents.agents.managers.research_manager import create_research_manager

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())
    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=23)
    _patch_io(monkeypatch, universe, returns)
    patch_contract_alpha_probe(monkeypatch, universe)

    state = _full_state()
    state["universe_path"] = str(universe_path)
    state["as_of_date"] = "2026-05-28"
    state["config"] = {"allocation_contract_enabled": True}

    stage2_out = create_research_manager(deep_llm=None)(state)
    rd = stage2_out["research_decision"]
    bt = stage2_out["bucket_target"]

    assert rd.allocation_contract is not None
    assert bt.weights == rd.allocation_contract.feasible_weights
    assert abs(sum(bt.weights.values()) - 1.0) < 1e-5
    assert rd.allocation_contract.envelope

    state.update(stage2_out)
    state["technical_report"] = make_technical_report(make_factor_panel(tickers))
    state["macro_report"] = make_macro_report()
    state["risk_report"] = make_risk_report()
    state["capital_krw"] = 1_000_000_000

    stage3_out = create_portfolio_allocator()(state)
    attr = stage3_out["allocation_attribution"]

    assert attr["cash_spillover"].get("skipped") is True
    assert attr["cash_spillover"].get("reason") == "bucket_sync_contract"
    assert "bucket_sync_audit" in attr
    assert attr["method_picker"]["rule_fired"] == "contract_fixed_method"
    assert attr["method_picker"]["method"] == OptimizationMethod.HRP.value

    align = attr["implementation_alignment"]
    assert align["feasible_weights"] == rd.allocation_contract.feasible_weights
    assert "prior_weights" in align
    prior_cfg = attr["config"]["bucket_target_prior"]
    ac = rd.allocation_contract
    assert prior_cfg["bond_tips_share"] == ac.bond_tips_share
    for b, w in ac.prior_weights.items():
        assert prior_cfg[b] == w

    cfg = attr["config"]
    stage2_bt = {
        k: v for k, v in cfg["bucket_target_stage2"].items() if k != "bond_tips_share"
    }
    assert cfg["bucket_target"] == stage2_bt
    assert cfg["bond_tips_share"] == cfg["bucket_target_stage2"]["bond_tips_share"]
    assert "bucket_target_post_spillover" not in cfg


def test_stage2_prior_differs_from_feasible_when_thin_bucket(tmp_path, monkeypatch):
    """Investability projection: empty bucket in universe → feasible < prior on that leg."""
    from tests.integration._allocator_state_helpers import (
        BUCKET_CATEGORIES,
        make_factor_panel,
        make_macro_report,
        make_risk_report,
        make_synthetic_returns,
        make_synthetic_universe,
        make_technical_report,
        patch_contract_alpha_probe,
    )
    from tests.unit.agents.test_research_manager_factor_model import _full_state
    from tradingagents.agents.allocator.portfolio_allocator import (
        create_portfolio_allocator,
    )
    from tradingagents.agents.managers.research_manager import create_research_manager

    universe = make_synthetic_universe(n_per_bucket=4)
    pm_cat, _, pm_sub = BUCKET_CATEGORIES["precious_metals"]
    universe.etfs = [
        e for e in universe.etfs
        if not (e.category == pm_cat and e.sub_category == pm_sub)
    ]
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())
    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=29)
    _patch_io(monkeypatch, universe, returns)
    patch_contract_alpha_probe(monkeypatch, universe)

    state = _full_state()
    state["universe_path"] = str(universe_path)
    state["as_of_date"] = "2026-05-28"
    state["config"] = {
        "allocation_contract_enabled": True,
        "contract_single_etf_cap": 0.20,
    }

    stage2_out = create_research_manager(deep_llm=None)(state)
    rd = stage2_out["research_decision"]
    contract = rd.allocation_contract
    assert contract is not None

    prior_pm = contract.prior_weights.get("precious_metals", 0.0)
    feas_pm = contract.feasible_weights.get("precious_metals", 0.0)
    if prior_pm > 1e-6:
        assert feas_pm < prior_pm or contract.binding_stage2.get("precious_metals")

    state.update(stage2_out)
    state["technical_report"] = make_technical_report(make_factor_panel(tickers))
    state["macro_report"] = make_macro_report()
    state["risk_report"] = make_risk_report()

    stage3_out = create_portfolio_allocator()(state)
    assert stage3_out["allocation_attribution"]["implementation_alignment"] is not None
