"""cluster_caps EF group constraint wire — 권고 3."""
import numpy as np
import pandas as pd

from tradingagents.agents.allocator.overlay_apply import apply_risk_overlay
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay
from tradingagents.schemas.technical import Cluster


_TICKERS = [f"A{i:03d}" for i in range(1, 11)]


def _wv():
    return WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in _TICKERS},
        rationale="1st",
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
    cols = {t: rng.normal(0.0005, 0.005 + i * 0.001, 300)
            for i, t in enumerate(_TICKERS)}
    return pd.DataFrame(cols, index=idx)


def test_cluster_caps_constrain_cluster_sum():
    """A001+A002 가 한 cluster (kr_equity bucket 동일). cluster_cap=0.30 → 합 ≤ 0.30."""
    # bucket kr_equity target = 0.20, 즉 A001+A002 합 = 0.20 → cluster cap 0.30 은 redundant.
    # 더 strict 케이스: cluster_cap=0.15 < bucket 0.20 → bucket equality 와 충돌 → escalate.
    # 여기서는 redundant case 로 정상 작동 확인.
    overlay = RiskOverlay(
        cluster_caps={"c_kr": 0.30}, risk_asset_multiplier=1.0,
        strength_applied=0.5, severity_decision="test",
    )
    clusters = [Cluster(
        cluster_id="c_kr", members=["A001", "A002"],
        avg_internal_correlation=0.85, category_label="KR equity",
    )]
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=clusters,
    )
    assert outcome == "primary_success"
    cluster_total = wv2.weights.get("A001", 0) + wv2.weights.get("A002", 0)
    assert cluster_total <= 0.30 + 1e-6


def test_cluster_caps_skipped_when_members_not_in_universe():
    """cluster.members 가 candidate set 에 없으면 constraint 추가 skip → 정상 풀이."""
    overlay = RiskOverlay(
        cluster_caps={"c_ghost": 0.01},
        strength_applied=0.5, severity_decision="test",
    )
    clusters = [Cluster(
        cluster_id="c_ghost", members=["GHOST1", "GHOST2"],
        avg_internal_correlation=0.85, category_label="not in universe",
    )]
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=clusters,
    )
    assert outcome == "primary_success"


def test_cluster_caps_drop_when_strict_conflict_with_bucket():
    """매우 엄격한 cluster_cap (< bucket target) → drop_level=1 (relax_cluster) escalate."""
    overlay = RiskOverlay(
        cluster_caps={"c_kr": 0.05},  # bucket kr_equity=0.20 인데 cap 0.05 → 충돌
        strength_applied=1.0, severity_decision="test",
    )
    clusters = [Cluster(
        cluster_id="c_kr", members=["A001", "A002"],
        avg_internal_correlation=0.85, category_label="KR equity",
    )]
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=clusters,
    )
    # cluster_cap 0.05 vs bucket equality 0.20 충돌 → cluster drop 후 정상
    assert outcome == "relax_cluster"
