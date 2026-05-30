"""Phase 3b BL views adapter — integration tests."""
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
    SINGLE_ASSET_CAP, create_portfolio_allocator,
)


def _setup_state_bl(
    tmp_path,
    monkeypatch,
    *,
    scenario: str = "goldilocks",
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


def test_allocator_with_method_bl_runs_to_completion(tmp_path, monkeypatch):
    """state['force_method']='black_litterman' 정상 종료, weight sum=1."""
    state = _setup_state_bl(tmp_path, monkeypatch, force_method="black_litterman")
    result = create_portfolio_allocator()(state)
    weights = result["weight_vector"].weights
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-4)


def test_allocator_bl_attribution_records_breakdown(tmp_path, monkeypatch):
    """force_method='black_litterman' + _bl_trigger=True → bl_views_breakdown 기록."""
    # _bl_trigger=True 가 되려면 force_method 대신 picker 경유해야 함.
    # force_method 는 rule_fired='state_override', params={} → _bl_trigger=False → legacy path.
    # 따라서 picker 경유 (high confidence goldilocks) 로 BL 트리거:
    state = _setup_state_bl(
        tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.8,
    )
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    opt = attr.get("optimization", {})
    assert "bl_views_breakdown" in opt
    bd = opt["bl_views_breakdown"]
    assert bd["scenario"] == "goldilocks"
    assert bd["n_views_per_bucket"]
    assert bd["rulebook_returns_used"]


def test_allocator_bl_respects_single_asset_cap(tmp_path, monkeypatch):
    """단일 자산 weight ≤ SINGLE_ASSET_CAP."""
    state = _setup_state_bl(tmp_path, monkeypatch, force_method="black_litterman")
    result = create_portfolio_allocator()(state)
    weights = result["weight_vector"].weights
    for ticker, w in weights.items():
        assert w <= SINGLE_ASSET_CAP + 1e-4, f"{ticker} weight {w} exceeds cap"


def test_allocator_bl_high_confidence_triggers_via_picker(tmp_path, monkeypatch):
    """regime_confidence=0.8 + goldilocks → picker rule_fired=bl_high_confidence."""
    state = _setup_state_bl(
        tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.8,
    )
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] == "black_litterman"
    assert mp["rule_fired"] == "bl_high_confidence"


def test_allocator_bl_low_confidence_falls_through_to_scenario_mapping(tmp_path, monkeypatch):
    """regime_confidence=0.5 → BL 미발동, scenario_mapping rule 로 HRP."""
    state = _setup_state_bl(
        tmp_path, monkeypatch, scenario="goldilocks", regime_confidence=0.5,
    )
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] != "black_litterman"
    assert mp["rule_fired"] == "scenario_mapping"


def test_allocator_bl_unknown_scenario_with_force_method_falls_back(tmp_path, monkeypatch):
    """force_method=black_litterman → _bl_trigger=False (state_override params={}) → historical 폴백."""
    # force_method='black_litterman' 은 state_override rule(-1), params={}.
    # _bl_trigger=False → legacy path: views={} → bl_views_fallback 기록.
    state = _setup_state_bl(
        tmp_path, monkeypatch, force_method="black_litterman", scenario="goldilocks",
    )
    # research_decision 제거해 scenario=None 경로 보장
    state["research_decision"] = None
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    opt = attr.get("optimization", {})
    assert opt.get("bl_views_fallback") == "empty_views_historical_fallback"


def test_allocator_bl_vs_hrp_different_method_labels(tmp_path, monkeypatch):
    """동일 입력에 force_method='black_litterman' vs 'hrp' → 다른 method 라벨."""
    state_bl = _setup_state_bl(tmp_path, monkeypatch, force_method="black_litterman")
    state_hrp = _setup_state_bl(tmp_path, monkeypatch, force_method="hrp")
    res_bl = create_portfolio_allocator()(state_bl)
    res_hrp = create_portfolio_allocator()(state_hrp)
    mp_bl = res_bl["allocation_attribution"]["method_picker"]
    mp_hrp = res_hrp["allocation_attribution"]["method_picker"]
    assert mp_bl["method"] == "black_litterman"
    assert mp_hrp["method"] == "hrp"
