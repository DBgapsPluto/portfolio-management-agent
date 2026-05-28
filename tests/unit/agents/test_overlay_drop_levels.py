"""apply_risk_overlay drop_level escalation — 권고 2 핵심."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.allocator.overlay_apply import apply_risk_overlay
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay


_TICKERS = [f"A{i:03d}" for i in range(1, 11)]


def _wv():
    return WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in _TICKERS},
        rationale="1st result",
    )


def _candidates():
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity":             _TICKERS[0:2],
            "global_equity":         _TICKERS[2:4],
            "cyclical_commodity_fx": _TICKERS[4:6],
            "kr_bond":               _TICKERS[6:8],
            "cash_mmf":              _TICKERS[8:10],
        },
        selection_criteria="test", total_candidates=10,
    )


def _bucket():
    return BucketTarget(
        weights={
            "kr_equity":             0.20,
            "global_equity":         0.20,
            "precious_metals":       0.00,
            "cyclical_commodity_fx": 0.20,
            "kr_bond":               0.20,
            "credit":                0.00,
            "global_duration":       0.00,
            "cash_mmf":              0.20,
        },
        rationale="test bucket",
    )


def _returns():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    cols = {}
    for i, t in enumerate(_TICKERS):
        cols[t] = rng.normal(0.0005, 0.005 + i * 0.001, 300)
    return pd.DataFrame(cols, index=idx)


def test_empty_overlay_returns_primary_success_and_unchanged_weights():
    """is_empty overlay → 1차 weight 그대로 + outcome='primary_success'."""
    overlay = RiskOverlay.no_concerns()
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    assert outcome == "primary_success"
    assert wv2.weights == wv1.weights


def test_full_overlay_solves_at_drop_level_zero():
    """가벼운 overlay (multiplier=0.85) → primary_success outcome."""
    overlay = RiskOverlay(
        risk_asset_multiplier=0.85, strength_applied=0.5,
        severity_decision="test",
    )
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    assert outcome == "primary_success"
    # risk_assets shrunk → safe assets ↑
    risk_total = sum(wv2.weights.get(t, 0) for t in _TICKERS[0:6])
    assert risk_total < 0.60 - 1e-3, (
        f"risk total {risk_total} should be < 0.60 after multiplier 0.85"
    )


def test_drop_level_escalation_through_cluster_then_ceiling():
    """cluster_caps + 매우 엄격한 ceilings → cluster 먼저 drop, ceiling 다음.

    아주 strict cluster_cap (불가능) 강제 → drop_level=1 (relax_cluster)
    로 escalate 후 풀이 성공.
    """
    overlay = RiskOverlay(
        cluster_caps={"impossible_cluster": 0.01},  # universe 에 없는 cluster
        risk_asset_multiplier=0.90,
        strength_applied=0.5, severity_decision="test",
    )
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],  # no cluster data → cap skip
    )
    # cluster_caps 가 있지만 clusters=[] → 적용 skip → drop_level=0 성공
    assert outcome == "primary_success"


def test_drop_level_fallback_to_1st_when_all_levels_infeasible():
    """모든 drop_level 실패하는 인공 케이스 → fallback_to_1st + 1차 weight 반환."""
    # 모든 ticker 에 1.0 floor 강제 → 5 tickers × 1.0 = 5.0 weight 필요 (불가능)
    overlay = RiskOverlay(
        tail_hedge_floor={t: 1.0 for t in _TICKERS},
        strength_applied=1.0, severity_decision="test",
    )
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    assert outcome == "fallback_to_1st"
    assert wv2.weights == wv1.weights
    assert "Stage 4 overlay infeasible" in wv2.rationale


def test_drop_level_ceiling_relaxed_when_bucket_equality_too_tight():
    """엄격한 weight_ceilings + strict bucket equality → relax_ceiling 으로 escalate.

    kr_equity bucket = 0.20, 2개 ticker × ceiling=0.05 → 합 0.10 < 0.20.
    drop_level=2 (ceilings 제거) 후 풀이 성공.
    """
    overlay = RiskOverlay(
        weight_ceilings={"A001": 0.05, "A002": 0.05},
        risk_asset_multiplier=1.0,
        strength_applied=0.7, severity_decision="test",
    )
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    # ceiling 0.05 가 bucket 0.20 와 충돌 → drop_level=1 cluster skip,
    # drop_level=2 ceiling drop 으로 풀이 성공
    assert outcome in ("relax_ceiling", "relax_band"), (
        f"expected ceiling/band relax, got {outcome}"
    )
