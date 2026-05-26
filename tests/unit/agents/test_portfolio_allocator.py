"""Tests for PortfolioAllocator (D4 + D12 + D13)."""
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator, _hrp_per_bucket, _build_sector_mapper_and_bounds,
    _apply_min_weight_threshold,
)
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod,
)
from tradingagents.skills.portfolio.method_picker import MethodChoice


def _bucket_target() -> BucketTarget:
    return BucketTarget(
        kr_equity=0.20, global_equity=0.30, fx_commodity=0.10,
        bond=0.30, cash_mmf=0.10,
        rationale="test",
    )


def _candidates() -> CandidateSet:
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A069500"],
            "global_equity": ["A360750"],
            "fx_commodity": ["A411060"],
            "bond": ["A114260"],
            "cash_mmf": ["A459580"],
        },
        selection_criteria="test",
        total_candidates=5,
    )


def test_hrp_per_bucket_single_asset_per_bucket():
    """When each bucket has 1 ticker, HRP allocation = 100% within bucket × bucket weight."""
    rng = np.random.default_rng(42)
    n = 252
    returns = pd.DataFrame({
        "A069500": rng.normal(0.001, 0.01, n),
        "A360750": rng.normal(0.001, 0.01, n),
        "A411060": rng.normal(0.001, 0.01, n),
        "A114260": rng.normal(0.0005, 0.005, n),
        "A459580": rng.normal(0.0001, 0.001, n),
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
            "global_equity": [], "fx_commodity": [], "bond": [], "cash_mmf": [],
        },
        selection_criteria="test", total_candidates=4,
    )
    target = BucketTarget(
        kr_equity=0.80, global_equity=0.0, fx_commodity=0.0,
        bond=0.20, cash_mmf=0.0,
        rationale="extreme test",
    )
    # We need a 5th asset for bond=0.20 to be filled, otherwise total < 1.0
    # Add a bond asset:
    candidates.bucket_to_tickers["bond"] = ["B1"]
    candidates = candidates.model_copy(update={"total_candidates": 5})

    rng = np.random.default_rng(0)
    n = 200
    # Assets in kr_equity highly correlated (HRP gives uneven weights)
    factor = rng.normal(0, 1, n)
    returns = pd.DataFrame({
        "A1": factor * 1.0 + rng.normal(0, 0.01, n),
        "A2": factor * 0.5 + rng.normal(0, 0.05, n),
        "A3": factor * 0.3 + rng.normal(0, 0.08, n),
        "A4": factor * 0.2 + rng.normal(0, 0.1, n),
        "B1": rng.normal(0, 0.005, n),
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
    """bond_tips_share > 0이면 bond bucket이 bond_tips + bond_nominal로 split."""
    candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": [], "global_equity": [], "fx_commodity": [],
            "bond": ["A_TIPS_1", "A_TIPS_2", "A_NOM_1", "A_NOM_2"],
            "cash_mmf": [],
        },
        selection_criteria="test", total_candidates=4,
    )
    target = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.40, cash_mmf=0.60, rationale="t",
        bond_tips_share=0.75,  # 40% bond × 75% = 30% TIPS, 10% nominal
    )
    sub_lookup = {
        "A_TIPS_1": "inflation_linked",
        "A_TIPS_2": "inflation_linked",
        "A_NOM_1": "kr_treasury",
        "A_NOM_2": "kr_corporate",
    }
    sm, lower, upper = _build_sector_mapper_and_bounds(
        candidates, target, attempts=0, sub_category_lookup=sub_lookup,
    )
    assert sm["A_TIPS_1"] == "bond_tips"
    assert sm["A_TIPS_2"] == "bond_tips"
    assert sm["A_NOM_1"] == "bond_nominal"
    assert sm["A_NOM_2"] == "bond_nominal"
    assert "bond" not in lower
    assert lower["bond_tips"] == pytest.approx(0.30)
    assert lower["bond_nominal"] == pytest.approx(0.10)


def test_sector_mapper_keeps_single_bond_when_tips_share_zero():
    """bond_tips_share = 0 (default)이면 기존 동작 그대로."""
    candidates = _candidates()
    target = _bucket_target()  # bond_tips_share=0 default
    sm, lower, upper = _build_sector_mapper_and_bounds(
        candidates, target, attempts=0, sub_category_lookup={},
    )
    assert sm["A114260"] == "bond"  # single bond
    assert lower["bond"] == 0.30


def test_sector_mapper_absorbs_missing_tips_pool():
    """후보에 inflation_linked 없으면 bond_tips target을 bond_nominal로 흡수."""
    candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": [], "global_equity": [], "fx_commodity": [],
            "bond": ["A_NOM_1", "A_NOM_2"],  # TIPS 0개
            "cash_mmf": [],
        },
        selection_criteria="test", total_candidates=2,
    )
    target = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.50, cash_mmf=0.50, rationale="t",
        bond_tips_share=0.80,  # 의도는 TIPS 40%, 그러나 후보 없음
    )
    sub_lookup = {"A_NOM_1": "kr_treasury", "A_NOM_2": "kr_corporate"}
    sm, lower, upper = _build_sector_mapper_and_bounds(
        candidates, target, attempts=0, sub_category_lookup=sub_lookup,
    )
    # bond_tips는 후보 없어서 target에서 제거, 모두 bond_nominal
    assert "bond_tips" not in lower
    assert lower["bond_nominal"] == pytest.approx(0.50)


def test_hrp_per_bucket_enforces_bond_tips_split():
    """HRP path가 bond_tips_share를 sub-pool weight으로 강제.

    Realistic setup: bond=0.40, tips_share=0.50 → TIPS 20%, nominal 20%.
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
            "kr_equity": [], "global_equity": [], "fx_commodity": [],
            "bond": ["A_TIPS_1", "A_TIPS_2", "A_NOM_1", "A_NOM_2"],
            "cash_mmf": ["A_CASH_1", "A_CASH_2", "A_CASH_3"],
        },
        selection_criteria="t", total_candidates=7,
    )
    target = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.40, cash_mmf=0.60, rationale="t",
        bond_tips_share=0.50,  # bond 40% × 50% = 20% TIPS, 20% nominal
    )
    sub_lookup = {
        "A_TIPS_1": "inflation_linked", "A_TIPS_2": "inflation_linked",
        "A_NOM_1": "kr_treasury", "A_NOM_2": "kr_treasury",
    }
    wv = _hrp_per_bucket(returns, candidates, target, sub_category_lookup=sub_lookup)
    tips_sum = wv.weights.get("A_TIPS_1", 0) + wv.weights.get("A_TIPS_2", 0)
    nom_sum = wv.weights.get("A_NOM_1", 0) + wv.weights.get("A_NOM_2", 0)
    # bond_tips_share=0.50 of bond 40% = 20% TIPS
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
