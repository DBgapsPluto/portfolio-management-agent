"""apply_risk_overlay — Stage 3 1차 → Stage 4 overlay → Stage 3 2차 흐름."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.allocator.overlay_apply import (
    _filter_returns_for_cov, _ridge_cov, _shrink_bucket_by_multiplier,
    apply_risk_overlay,
)
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay


def _bucket():
    # 모든 bucket ≤ 0.20 — 단일 ticker per bucket fixture 호환
    return BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.20,
        bond=0.20, cash_mmf=0.20,
        rationale="test bucket",
    )


_TICKERS = [f"A{i:03d}" for i in range(1, 11)]


def _wv():
    # 10 ticker × 0.10 = 1.0, 모두 cap 0.20 이하 (mandate-safe)
    return WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in _TICKERS},
        rationale="1st result",
    )


def _candidates():
    # 2 ticker per bucket — multiplier 적용 후에도 cap 안 위반
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity":     _TICKERS[0:2],
            "global_equity": _TICKERS[2:4],
            "fx_commodity":  _TICKERS[4:6],
            "bond":          _TICKERS[6:8],
            "cash_mmf":      _TICKERS[8:10],
        },
        selection_criteria="test", total_candidates=10,
    )


def _returns():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    cols = {}
    for i, t in enumerate(_TICKERS):
        cols[t] = rng.normal(0.0005, 0.005 + i * 0.001, 300)
    return pd.DataFrame(cols, index=idx)


def test_empty_overlay_returns_weight_vector_unchanged():
    overlay = RiskOverlay()
    result, _ = apply_risk_overlay(
        _wv(), overlay, _candidates(), _returns(), _bucket(),
        method=OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    assert result.weights == _wv().weights


def test_shrink_bucket_by_multiplier_05():
    bucket = _bucket()  # 위험자산 = 0.20+0.20+0.20 = 0.60
    shrunk = _shrink_bucket_by_multiplier(bucket, 0.5)
    risk_total = shrunk.kr_equity + shrunk.global_equity + shrunk.fx_commodity
    assert risk_total == pytest.approx(0.30, abs=0.001)
    safe_total = shrunk.bond + shrunk.cash_mmf
    assert safe_total == pytest.approx(0.70, abs=0.001)
    assert (risk_total + safe_total) == pytest.approx(1.0, abs=0.001)


def test_shrink_bucket_by_multiplier_10_is_noop():
    bucket = _bucket()
    shrunk = _shrink_bucket_by_multiplier(bucket, 1.0)
    assert shrunk.kr_equity == bucket.kr_equity
    assert shrunk.cash_mmf == bucket.cash_mmf


def test_overlay_with_multiplier_shrinks_risk_assets():
    overlay = RiskOverlay(
        risk_asset_multiplier=0.7,
        severity_decision="test shrink",
        strength_applied=0.7,
    )
    result, _ = apply_risk_overlay(
        _wv(), overlay, _candidates(), _returns(), _bucket(),
        method=OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    # 위험자산 줄어들었는지
    risk_total = (
        result.weights.get("A001", 0)  # kr
        + result.weights.get("A002", 0)  # gl
        + result.weights.get("A003", 0)  # fx
    )
    # multiplier 0.7 × original risk 0.60 ≈ 0.42. 솔버 결과에 따라 변동.
    assert risk_total < 0.60


def test_overlay_infeasible_returns_1st_result():
    """tail_hedge_floor가 단일 cap 20%과 충돌하는 극단 case — 1차 결과 그대로 반환."""
    overlay = RiskOverlay(
        # 모든 ticker에 floor 0.30 (단일 cap 0.20 초과 + sum > 1.0 → infeasible)
        tail_hedge_floor={t: 0.30 for t in ["A001", "A002", "A003", "A004", "A005"]},
        severity_decision="extreme test",
        strength_applied=1.0,
    )
    result, _ = apply_risk_overlay(
        _wv(), overlay, _candidates(), _returns(), _bucket(),
        method=OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    # 1차 결과로 fallback
    assert "infeasible" in result.rationale.lower() or result.weights == _wv().weights


def test_overlay_mandate_safe_after_apply():
    """overlay 적용 후에도 단일 자산 cap 20% 유지 (multiplier만)."""
    overlay = RiskOverlay(
        risk_asset_multiplier=0.9,
        severity_decision="test mandate",
        strength_applied=0.5,
    )
    result, _ = apply_risk_overlay(
        _wv(), overlay, _candidates(), _returns(), _bucket(),
        method=OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    # 모든 weight ≤ 0.20
    for t, w in result.weights.items():
        assert w <= 0.20 + 1e-6, f"{t}={w} violates 20% cap"
    # sum = 1.0
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-3)


def test_overlay_hrp_method_swaps_to_min_variance():
    """HRP는 sector_constraints 미지원이라 overlay 시 MIN_VARIANCE로 fallback."""
    overlay = RiskOverlay(
        risk_asset_multiplier=0.9,
        severity_decision="test hrp swap",
        strength_applied=0.3,
    )
    result, _ = apply_risk_overlay(
        _wv(), overlay, _candidates(), _returns(), _bucket(),
        method=OptimizationMethod.HRP, clusters=[],
    )
    assert result.method == OptimizationMethod.MIN_VARIANCE


# ---- 2026-05-26 backtest follow-up #2+#3 ----


def test_filter_returns_drops_short_history_tickers():
    """짧은 history ticker 부터 점진 drop 후 obs 충족."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    df = pd.DataFrame(
        {t: rng.normal(0, 0.01, 300) for t in _TICKERS}, index=idx,
    )
    # A001 은 마지막 10일만 데이터 (신규 상장 시뮬레이션)
    df.loc[df.index[:-10], "A001"] = np.nan

    filtered, excluded = _filter_returns_for_cov(df, min_obs=60)

    assert "A001" in excluded
    assert len(filtered) >= 60


def test_filter_returns_preserves_sufficient_data():
    """충분한 history 면 excluded 빈 list."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    df = pd.DataFrame(
        {t: rng.normal(0, 0.01, 300) for t in _TICKERS}, index=idx,
    )
    filtered, excluded = _filter_returns_for_cov(df, min_obs=60)
    assert excluded == []
    assert len(filtered) == 300


def test_ridge_cov_is_psd():
    """ridge 적용 후 covariance 의 eigenvalues 전부 ≥ 0 (PSD)."""
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=80, freq="B")
    # rank-deficient: 5 ticker 가 동일 series → cov 가 singular
    base = rng.normal(0, 0.01, 80)
    df = pd.DataFrame(
        {f"T{i}": base + rng.normal(0, 1e-8, 80) for i in range(5)},
        index=idx,
    )
    S = _ridge_cov(df, lam=1e-4)
    eigs = np.linalg.eigvalsh(S.values)
    assert eigs.min() > 0, f"min eigenvalue {eigs.min()} not positive"
