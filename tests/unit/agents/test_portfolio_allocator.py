"""Tests for PortfolioAllocator (D4 + D12 + D13)."""
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator, _hrp_per_bucket, _build_sector_mapper_and_bounds,
    _apply_min_weight_threshold, _apply_subcategory_cap,
)
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod,
)
from tradingagents.skills.portfolio.method_picker import MethodChoice


def _bucket_target() -> BucketTarget:
    return BucketTarget(
        weights={
            "kr_equity":             0.20,
            "global_equity":         0.30,
            "precious_metals":       0.00,
            "cyclical_commodity_fx": 0.10,
            "kr_bond":               0.20,
            "credit":                0.10,
            "global_duration":       0.00,
            "cash_mmf":              0.10,
        },
        rationale="test",
    )


def _candidates() -> CandidateSet:
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity":             ["A069500"],
            "global_equity":         ["A360750"],
            "cyclical_commodity_fx": ["A411060"],
            "kr_bond":               ["A114260"],
            "credit":                ["A_CREDIT"],
            "cash_mmf":              ["A459580"],
        },
        selection_criteria="test",
        total_candidates=6,
    )


def test_hrp_per_bucket_single_asset_per_bucket():
    """When each bucket has 1 ticker, HRP allocation = 100% within bucket × bucket weight."""
    rng = np.random.default_rng(42)
    n = 252
    returns = pd.DataFrame({
        "A069500":  rng.normal(0.001, 0.01, n),
        "A360750":  rng.normal(0.001, 0.01, n),
        "A411060":  rng.normal(0.001, 0.01, n),
        "A114260":  rng.normal(0.0005, 0.005, n),
        "A_CREDIT": rng.normal(0.0003, 0.004, n),
        "A459580":  rng.normal(0.0001, 0.001, n),
    })
    wv = _hrp_per_bucket(returns, _candidates(), _bucket_target())
    # Each ticker gets its bucket target weight (since 1 ticker per bucket)
    assert wv.weights["A069500"] == pytest.approx(0.20, abs=0.01)
    assert wv.weights["A360750"] == pytest.approx(0.20, abs=0.01)  # capped from 0.30 to 0.20
    # Verify cap respected
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())


def test_hrp_per_bucket_iterative_redistribution():
    """REGRESSION (D12): iterative water-filling converges when single-pass fails.

    Bucket=0.80, 4 candidates with HRP weights (0.6, 0.2, 0.1, 0.1):
    scaled = (0.48, 0.16, 0.08, 0.08), sum 0.80
    Single-pass: cap → (0.20, 0.16, 0.08, 0.08) sum 0.52, residual 0.28 redistributed
                 → (0.20, 0.20, 0.173, 0.173) sum 0.747 (WRONG — bucket target 0.80 missed)
    Iterative: keeps redistributing until convergence.
    """
    # Simulate: single bucket with 4 tickers, target 0.80
    candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A1", "A2", "A3", "A4"],
            "global_equity": [], "cyclical_commodity_fx": [], "kr_bond": [],
            "credit": [], "global_duration": [], "cash_mmf": [],
        },
        selection_criteria="test", total_candidates=4,
    )
    target = BucketTarget(
        weights={
            "kr_equity":             0.80,
            "global_equity":         0.00,
            "precious_metals":       0.00,
            "cyclical_commodity_fx": 0.00,
            "kr_bond":               0.20,
            "credit":                0.00,
            "global_duration":       0.00,
            "cash_mmf":              0.00,
        },
        rationale="extreme test",
    )
    # We need a 5th asset for kr_bond=0.20 to be filled, otherwise total < 1.0
    # Add a kr_bond asset:
    candidates.bucket_to_tickers["kr_bond"] = ["B1"]
    candidates = candidates.model_copy(update={"total_candidates": 5})

    rng = np.random.default_rng(0)
    n = 200
    # Assets in kr_equity with different vol (HRP gives uneven weights), but NOT
    # perfectly correlated — keep some independent noise so HRP converges.
    factor = rng.normal(0, 1, n)
    # B1 must be in returns for kr_bond pool to be processed
    returns = pd.DataFrame({
        "A1": factor * 1.0 + rng.normal(0, 0.20, n),   # high vol
        "A2": factor * 0.5 + rng.normal(0, 0.15, n),
        "A3": factor * 0.3 + rng.normal(0, 0.10, n),
        "A4": factor * 0.2 + rng.normal(0, 0.08, n),   # low vol
        "B1": rng.normal(0, 0.005, n),                  # kr_bond ticker
    })
    wv = _hrp_per_bucket(returns, candidates, target)

    # All weights ≤ 0.20 cap
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
    # Bucket sum approximately reaches target (within iterative tolerance)
    kr_sum = sum(wv.weights[t] for t in ["A1", "A2", "A3", "A4"] if t in wv.weights)
    assert kr_sum >= 0.79, f"kr_equity bucket sum {kr_sum} < 0.79"


def test_sector_mapper_strict_then_relaxed():
    candidates = _candidates()
    target = _bucket_target()
    # Strict
    _, lower, upper = _build_sector_mapper_and_bounds(candidates, target, attempts=0)
    assert lower["kr_equity"] == upper["kr_equity"] == 0.20
    # Relaxed
    _, lower, upper = _build_sector_mapper_and_bounds(candidates, target, attempts=1)
    assert lower["kr_equity"] == 0.15  # 0.20 - 0.05
    assert upper["kr_equity"] == 0.25  # 0.20 + 0.05


def test_sector_mapper_splits_bond_when_tips_share_positive():
    """bond_tips_share > 0이면 bond bucket이 bond_tips + bond_nominal로 split.

    Phase 1 guard: cash_mmf 후보 필요 (없으면 cash 대상이 bond 로 흡수돼서 split 검증 흐트러짐).
    """
    candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": [], "global_equity": [], "cyclical_commodity_fx": [],
            "global_duration": ["A_TIPS_1", "A_TIPS_2", "A_NOM_1", "A_NOM_2"],
            "cash_mmf": ["A_CASH_1", "A_CASH_2", "A_CASH_3"],
        },
        selection_criteria="test", total_candidates=7,
    )
    target = BucketTarget(
        weights={
            "kr_equity":             0.00,
            "global_equity":         0.00,
            "precious_metals":       0.00,
            "cyclical_commodity_fx": 0.00,
            "kr_bond":               0.00,
            "credit":                0.00,
            "global_duration":       0.40,
            "cash_mmf":              0.60,
        },
        rationale="t",
        bond_tips_share=0.75,  # 40% global_duration × 75% = 30% TIPS, 10% nominal
    )
    sub_lookup = {
        "A_TIPS_1": "inflation_linked",
        "A_TIPS_2": "inflation_linked",
        "A_NOM_1": "us_treasury",
        "A_NOM_2": "us_aggregate",
    }
    sm, lower, upper = _build_sector_mapper_and_bounds(
        candidates, target, attempts=0, sub_category_lookup=sub_lookup,
    )
    assert sm["A_TIPS_1"] == "bond_tips"
    assert sm["A_TIPS_2"] == "bond_tips"
    assert sm["A_NOM_1"] == "bond_nominal"
    assert sm["A_NOM_2"] == "bond_nominal"
    assert "global_duration" not in lower
    assert lower["bond_tips"] == pytest.approx(0.30)
    assert lower["bond_nominal"] == pytest.approx(0.10)


def test_sector_mapper_keeps_single_bond_when_tips_share_zero():
    """bond_tips_share = 0 (default)이면 기존 동작 그대로."""
    candidates = _candidates()
    target = _bucket_target()  # bond_tips_share=0 default
    sm, lower, upper = _build_sector_mapper_and_bounds(
        candidates, target, attempts=0, sub_category_lookup={},
    )
    assert sm["A114260"] == "kr_bond"  # single kr_bond
    assert lower["kr_bond"] == pytest.approx(0.20)


def test_sector_mapper_cash_guard_absorbs_into_global_duration_when_not_split():
    """REGRESSION: cash-infeasibility guard must absorb cash into global_duration
    (the 8-bucket bond-equivalent) when split_bond is False — NOT a phantom 'bond' key.

    cash_mmf has positive target but too few candidate tickers to reach it under
    SINGLE_ASSET_CAP (1 ticker × 0.20 cap = 0.20 < 0.30 target) → guard fires. With
    bond_tips_share=0 (no split), the raw 8-bucket weights have 'global_duration',
    not 'bond'. The absorbed cash weight must land in global_duration; a phantom
    'bond' key would silently drop the weight (no ticker maps to it).
    """
    candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A_EQ_1"],
            "global_duration": ["A_DUR_1", "A_DUR_2"],
            "cash_mmf": ["A_CASH_1"],  # 1개뿐 → 1 × 0.20 cap = 0.20 < 0.30 target
        },
        selection_criteria="test", total_candidates=4,
    )
    target = BucketTarget(
        weights={
            "kr_equity":             0.50,
            "global_equity":         0.00,
            "precious_metals":       0.00,
            "cyclical_commodity_fx": 0.00,
            "kr_bond":               0.00,
            "credit":                0.00,
            "global_duration":       0.20,
            "cash_mmf":              0.30,
        },
        rationale="t",
        bond_tips_share=0.0,  # split_bond False
    )
    sm, lower, upper = _build_sector_mapper_and_bounds(
        candidates, target, attempts=0,
    )
    # 흡수 후 phantom 'bond' 키가 없어야 함
    assert "bond" not in lower
    assert "bond" not in upper
    assert "bond" not in sm.values()
    # cash_mmf target은 제거되고 global_duration이 흡수 (0.30 + 0.20 = 0.50)
    assert "cash_mmf" not in lower
    assert lower["global_duration"] == pytest.approx(0.50)
    assert upper["global_duration"] == pytest.approx(0.50)


def test_sector_mapper_absorbs_missing_tips_pool():
    """후보에 inflation_linked 없으면 bond_tips target을 bond_nominal로 흡수.

    Phase 1 guard: cash_mmf 후보 필요 (없으면 cash 가 bond 로 흡수돼서 nominal 합산 변경).
    """
    candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": [], "global_equity": [], "cyclical_commodity_fx": [],
            "global_duration": ["A_NOM_1", "A_NOM_2"],  # TIPS 0개
            "cash_mmf": ["A_CASH_1", "A_CASH_2", "A_CASH_3"],
        },
        selection_criteria="test", total_candidates=5,
    )
    target = BucketTarget(
        weights={
            "kr_equity":             0.00,
            "global_equity":         0.00,
            "precious_metals":       0.00,
            "cyclical_commodity_fx": 0.00,
            "kr_bond":               0.00,
            "credit":                0.00,
            "global_duration":       0.50,
            "cash_mmf":              0.50,
        },
        rationale="t",
        bond_tips_share=0.80,  # 의도는 TIPS 40%, 그러나 후보 없음
    )
    sub_lookup = {"A_NOM_1": "us_treasury", "A_NOM_2": "us_aggregate"}
    sm, lower, upper = _build_sector_mapper_and_bounds(
        candidates, target, attempts=0, sub_category_lookup=sub_lookup,
    )
    # bond_tips는 후보 없어서 target에서 제거, 모두 bond_nominal
    assert "bond_tips" not in lower
    assert lower["bond_nominal"] == pytest.approx(0.50)


def test_hrp_per_bucket_enforces_bond_tips_split():
    """HRP path가 bond_tips_share를 sub-pool weight으로 강제.

    Realistic setup: global_duration=0.40, tips_share=0.50 → TIPS 20%, nominal 20%.
    Cash 3 tickers로 분산 (cap 0.20씩 → 3개 = 0.60 채움).
    """
    rng = np.random.default_rng(7)
    n = 252
    returns = pd.DataFrame({
        "A_TIPS_1": rng.normal(0.0005, 0.012, n),
        "A_TIPS_2": rng.normal(0.0005, 0.010, n),
        "A_NOM_1":  rng.normal(0.0003, 0.003, n),
        "A_NOM_2":  rng.normal(0.0003, 0.004, n),
        "A_CASH_1": rng.normal(0.0001, 0.001, n),
        "A_CASH_2": rng.normal(0.0001, 0.001, n),
        "A_CASH_3": rng.normal(0.0001, 0.001, n),
    })
    candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": [], "global_equity": [], "cyclical_commodity_fx": [],
            "kr_bond": [], "credit": [],
            "global_duration": ["A_TIPS_1", "A_TIPS_2", "A_NOM_1", "A_NOM_2"],
            "cash_mmf": ["A_CASH_1", "A_CASH_2", "A_CASH_3"],
        },
        selection_criteria="t", total_candidates=7,
    )
    target = BucketTarget(
        weights={
            "kr_equity":             0.00,
            "global_equity":         0.00,
            "precious_metals":       0.00,
            "cyclical_commodity_fx": 0.00,
            "kr_bond":               0.00,
            "credit":                0.00,
            "global_duration":       0.40,
            "cash_mmf":              0.60,
        },
        rationale="t",
        bond_tips_share=0.50,  # global_duration 40% × 50% = 20% TIPS, 20% nominal
    )
    sub_lookup = {
        "A_TIPS_1": "inflation_linked", "A_TIPS_2": "inflation_linked",
        "A_NOM_1": "us_treasury", "A_NOM_2": "us_treasury",
    }
    wv = _hrp_per_bucket(returns, candidates, target, sub_category_lookup=sub_lookup)
    tips_sum = wv.weights.get("A_TIPS_1", 0) + wv.weights.get("A_TIPS_2", 0)
    nom_sum = wv.weights.get("A_NOM_1", 0) + wv.weights.get("A_NOM_2", 0)
    # bond_tips_share=0.50 of global_duration 40% = 20% TIPS
    assert tips_sum == pytest.approx(0.20, abs=0.03), f"TIPS sum {tips_sum} != 0.20"
    assert nom_sum == pytest.approx(0.20, abs=0.03), f"nominal sum {nom_sum} != 0.20"


# ---- 2026-05-26 #2 fix: min weight threshold ----


def _candidate_set_two_bucket():
    return CandidateSet(
        bucket_to_tickers={
            "fx_commodity": ["A_FX1", "A_FX2", "A_GOLD"],
            "bond": ["A_BOND1", "A_BOND2", "A_BOND3", "A_BOND4", "A_BOND5"],
        },
        selection_criteria="t", total_candidates=8,
    )


def test_min_weight_threshold_drops_dust_position():
    """0.17% (원유 케이스) 같은 dust 는 drop + 같은 bucket 재분배.

    Input precondition: 모든 weight ≤ SINGLE_ASSET_CAP (0.20).
    """
    weights = {
        "A_FX1": 0.18, "A_FX2": 0.165, "A_GOLD": 0.005,  # gold dust
        "A_BOND1": 0.16, "A_BOND2": 0.165, "A_BOND3": 0.16,
        "A_BOND4": 0.16, "A_BOND5": 0.005,  # A_BOND5 도 dust (bond bucket)
    }
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    cs = _candidate_set_two_bucket()
    attribution: dict = {}
    new_w = _apply_min_weight_threshold(weights, cs, attribution=attribution)
    assert "A_GOLD" not in new_w, "fx dust not dropped"
    assert "A_BOND5" not in new_w, "bond dust not dropped"
    assert "min_weight_dropped" in attribution
    assert "A_GOLD" in attribution["min_weight_dropped"]
    assert "A_BOND5" in attribution["min_weight_dropped"]
    # Sum 보존 (1.0)
    assert sum(new_w.values()) == pytest.approx(1.0, abs=1e-6)
    # 같은 bucket 의 survivors 가 dust 흡수
    assert new_w["A_FX1"] > 0.18
    assert new_w["A_FX2"] > 0.165
    assert new_w["A_BOND1"] > 0.16


def test_min_weight_threshold_no_op_when_all_above():
    """모든 weight 가 threshold 이상이면 no-op."""
    weights = {"A_FX1": 0.18, "A_FX2": 0.18, "A_BOND1": 0.18,
               "A_BOND2": 0.18, "A_BOND3": 0.18, "A_BOND4": 0.10}
    cs = _candidate_set_two_bucket()
    new_w = _apply_min_weight_threshold(weights, cs)
    assert new_w == weights


def test_min_weight_threshold_redistributes_to_global_when_bucket_empty():
    """같은 bucket 의 survivors 없으면 전체 survivors 에 비례 redistribute."""
    weights = {
        "A_FX1": 0.005, "A_FX2": 0.005, "A_GOLD": 0.005,  # 전 fx bucket dust
        "A_BOND1": 0.197, "A_BOND2": 0.197, "A_BOND3": 0.197,
        "A_BOND4": 0.197, "A_BOND5": 0.197,
    }
    cs = _candidate_set_two_bucket()
    new_w = _apply_min_weight_threshold(weights, cs)
    assert "A_FX1" not in new_w
    assert "A_GOLD" not in new_w
    assert sum(new_w.values()) == pytest.approx(1.0, abs=1e-6)


# ---- 2026-05-26 fix-A: sub_category cap ----


def _candidate_set_fx_test():
    return CandidateSet(
        bucket_to_tickers={
            "fx_commodity": ["A_JPY", "A_USD", "A_GOLD", "A_OIL"],
        },
        selection_criteria="t", total_candidates=4,
    )


def test_subcategory_cap_reduces_dominant_subcat():
    """단일 sub_category 가 bucket 50% 초과 → cap + 다른 sub_cat 으로 redistribute."""
    weights = {
        "A_JPY": 0.13,   # jpy_fx — 13%, bucket 19% 의 68%
        "A_USD": 0.03,   # usd_fx
        "A_GOLD": 0.02,  # gold
        "A_OIL": 0.01,   # oil
    }
    # bucket fx 합 = 0.19, jpy_fx 합 0.13 > 0.50 × 0.19 = 0.095
    sub_lookup = {
        "A_JPY": "jpy_fx", "A_USD": "usd_fx",
        "A_GOLD": "gold", "A_OIL": "oil_energy",
    }
    cs = _candidate_set_fx_test()
    attribution: dict = {}
    new_w = _apply_subcategory_cap(
        weights, cs, sub_category_lookup=sub_lookup, attribution=attribution,
    )
    # A_JPY 가 capped (bucket 19% × 50% = 9.5%)
    assert new_w["A_JPY"] == pytest.approx(0.19 * 0.5, abs=1e-6)
    # Sum 보존
    assert sum(new_w.values()) == pytest.approx(sum(weights.values()), abs=1e-6)
    # 다른 sub_cat 자산이 증가
    assert new_w["A_USD"] > 0.03
    assert new_w["A_GOLD"] > 0.02
    # attribution 기록
    assert "subcategory_capped" in attribution


def test_subcategory_cap_no_op_when_balanced():
    """모든 sub_category 가 50% 이하면 no-op."""
    weights = {
        "A_JPY": 0.05, "A_USD": 0.05, "A_GOLD": 0.05, "A_OIL": 0.04,
    }
    sub_lookup = {
        "A_JPY": "jpy_fx", "A_USD": "usd_fx",
        "A_GOLD": "gold", "A_OIL": "oil_energy",
    }
    cs = _candidate_set_fx_test()
    new_w = _apply_subcategory_cap(weights, cs, sub_category_lookup=sub_lookup)
    assert new_w == weights


def test_subcategory_cap_no_lookup_returns_unchanged():
    """sub_category_lookup=None 또는 빈 dict 면 변경 없음."""
    weights = {"A_JPY": 0.13, "A_USD": 0.06}
    cs = _candidate_set_fx_test()
    assert _apply_subcategory_cap(weights, cs, sub_category_lookup=None) == weights
    assert _apply_subcategory_cap(weights, cs, sub_category_lookup={}) == weights


def test_node_force_method_override_uses_state_value(tmp_path, monkeypatch):
    """state['force_method']='nco' 시 method_picker 호출 안 함, NCO 강제."""
    from datetime import date
    import pandas as pd
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=31)
    factor_panel = make_factor_panel(tickers)

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[[t for t in eligible if t in returns.columns]],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )
    state["force_method"] = "nco"

    result = create_portfolio_allocator()(state)
    method_picker = result["allocation_attribution"]["method_picker"]
    assert method_picker["method"] == "nco"
    assert method_picker["rule_fired"] == "state_override"


# ---------------------------------------------------------------------------
# Phase 4c — _apply_single_cap_redistribution unit tests
# ---------------------------------------------------------------------------
from tradingagents.agents.allocator.portfolio_allocator import (
    _apply_single_cap_redistribution,
)


def test_apply_single_cap_redistribution_basic():
    weights = {f"A{i:03d}": 0.10 for i in range(10)}
    out = _apply_single_cap_redistribution(weights, cap=0.20)
    assert all(0.0 <= w <= 0.20 + 1e-9 for w in out.values())
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_apply_single_cap_redistribution_cap_clipped_all():
    weights = {"A": 1/3, "B": 1/3, "C": 1/3}
    out = _apply_single_cap_redistribution(weights, cap=0.20)
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_apply_single_cap_redistribution_partial_cap():
    weights = {"A": 0.50, "B": 0.10, "C": 0.10, "D": 0.10, "E": 0.10, "F": 0.10}
    out = _apply_single_cap_redistribution(weights, cap=0.20)
    assert out["A"] <= 0.20 + 1e-9
    assert abs(sum(out.values()) - 1.0) < 1e-9
    for k in ["B", "C", "D", "E", "F"]:
        assert 0.15 <= out[k] <= 0.20 + 1e-9


def test_apply_single_cap_redistribution_iterative():
    weights = {"A": 0.80, "B": 0.05, "C": 0.05, "D": 0.05, "E": 0.05}
    out = _apply_single_cap_redistribution(weights, cap=0.20)
    assert all(w <= 0.20 + 1e-9 for w in out.values())
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_apply_single_cap_redistribution_empty():
    out = _apply_single_cap_redistribution({}, cap=0.20)
    assert out == {}


from tradingagents.agents.allocator.portfolio_allocator import (
    _optimize_with_bucket_constraints,
)


def test_optimizer_infeasibility_falls_back_to_min_volatility():
    """Stage 3 anchor-tuning: infeasible max_sharpe must NOT crash.

    All-negative mean returns make pypfopt max_sharpe() raise
    ("at least one of the assets must have an expected return exceeding the
    risk-free rate"), but min_volatility (which ignores mu) stays feasible.
    The node must gracefully fall back instead of raising RuntimeError.

    Pre-fix: this RAISES RuntimeError. Post-fix: graceful fallback.
    """
    rng = np.random.default_rng(7)
    n = 200
    # 1 ticker per bucket (matches _candidates / _bucket_target layout); all
    # drawn with NEGATIVE drift so mean_historical_return < risk-free rate.
    returns = pd.DataFrame({
        "A069500":  rng.normal(-0.001, 0.010, n),
        "A360750":  rng.normal(-0.001, 0.010, n),
        "A411060":  rng.normal(-0.001, 0.010, n),
        "A114260":  rng.normal(-0.001, 0.005, n),
        "A_CREDIT": rng.normal(-0.001, 0.004, n),
        "A459580":  rng.normal(-0.001, 0.002, n),
    })
    attribution: dict = {}
    # BLACK_LITTERMAN with empty views → mu = mean_historical_return (all neg)
    # → reaches ef.max_sharpe() which is infeasible.
    wv, sigma_df = _optimize_with_bucket_constraints(
        method=OptimizationMethod.BLACK_LITTERMAN,
        returns=returns,
        candidates=_candidates(),
        bucket_target=_bucket_target(),
        method_params={},  # no _bl_trigger, no views
        attempts=0,
        attribution=attribution,
    )

    # No RuntimeError raised → valid allocation produced.
    assert wv.weights, "fallback produced no weights"
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6, (
        f"weights must sum to 1, got {sum(wv.weights.values())}"
    )
    assert all(w >= 0 for w in wv.weights.values()), "weights must be non-negative"
    assert all(w <= 0.20 + 1e-4 for w in wv.weights.values()), "single-asset cap respected"
    # Fallback path recorded in attribution.
    assert "optimization_fallback" in attribution
    assert attribution["optimization_fallback"].startswith("max_sharpe_infeasible→")
