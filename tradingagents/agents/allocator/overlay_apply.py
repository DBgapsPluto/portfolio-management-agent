"""Stage 4 RiskOverlay를 Stage 3 optimizer 2차 호출의 constraint로 변환.

흐름:
  Stage 3 (1차, attempts=0) → WeightVector w1
  Stage 4 → RiskOverlay (lens debate + severity gate)
  apply_risk_overlay (이 모듈):
    overlay 비면 → w1 그대로
    overlay 차면 → 2차 optimizer (method 재사용, overlay 적용) → w2
  Stage 5 validator

Fallback 룰 (overlay infeasibility):
  1차 시도: 풀 강도 overlay
  2차 시도 (infeasible): 절반 강도 overlay
  최종 fallback: 1차 weight 그대로 반환 (overlay 무시, archive에 로그)

mandate constraint (단일 cap 20%, bucket sum, 위험자산 ≤ 0.70)는 변환 후에도
자동 보장 — overlay는 *추가 제약*만 만들고, optimizer가 모두 합쳐 풀이.
"""
from __future__ import annotations

import logging

import pandas as pd
from pypfopt import EfficientFrontier, HRPOpt, expected_returns, risk_models

from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay

logger = logging.getLogger(__name__)


def _shrink_bucket_by_multiplier(
    bucket_target: BucketTarget, multiplier: float,
) -> BucketTarget:
    """위험자산 multiplier 적용 — 줄어든 만큼 bond + mmf로 재정규화.

    multiplier=1.0 → no-op. multiplier<1.0 → 위험자산 shrink + safe assets ↑.
    """
    if multiplier >= 0.999:
        return bucket_target

    risk_assets_orig = (
        bucket_target.kr_equity + bucket_target.global_equity
        + bucket_target.fx_commodity
    )
    safe_assets_orig = bucket_target.bond + bucket_target.cash_mmf

    new_risk = risk_assets_orig * multiplier
    shrinkage = risk_assets_orig - new_risk

    # 줄어든 양을 bond:mmf=2:1로 분배 (mmf는 cash 성격이라 더 적게)
    if safe_assets_orig > 0:
        bond_share = bucket_target.bond / safe_assets_orig
        mmf_share = bucket_target.cash_mmf / safe_assets_orig
        new_bond = bucket_target.bond + shrinkage * bond_share
        new_mmf = bucket_target.cash_mmf + shrinkage * mmf_share
    else:
        # 안전 자산이 0이었으면 단순히 mmf로
        new_bond = bucket_target.bond + shrinkage * 0.6
        new_mmf = bucket_target.cash_mmf + shrinkage * 0.4

    # 비례로 위험자산 줄임
    risk_factor = new_risk / risk_assets_orig if risk_assets_orig > 0 else 0.0
    return BucketTarget(
        kr_equity=bucket_target.kr_equity * risk_factor,
        global_equity=bucket_target.global_equity * risk_factor,
        fx_commodity=bucket_target.fx_commodity * risk_factor,
        bond=new_bond,
        cash_mmf=new_mmf,
        rationale=(
            f"Stage 4 overlay shrink (×{multiplier:.2f}): "
            f"{bucket_target.rationale[:300]}"
        )[:500],
    )


def _build_per_ticker_bounds(
    tickers: list[str], overlay: RiskOverlay,
) -> dict[str, tuple[float, float]]:
    """ticker → (lower, upper). overlay에 명시된 ticker만 변경, 나머지는 (0, 0.20)."""
    bounds: dict[str, tuple[float, float]] = {}
    for t in tickers:
        upper = min(0.20, overlay.weight_ceilings.get(t, 0.20))
        lower = overlay.tail_hedge_floor.get(t, 0.0)
        if lower > upper:
            # 명백한 충돌 — floor 우선 (안전), upper 완화
            upper = lower + 1e-6
        bounds[t] = (lower, upper)
    return bounds


def _half_strength(overlay: RiskOverlay) -> RiskOverlay:
    """overlay 강도를 절반으로 (fallback용)."""
    half_ceilings = {
        t: min(0.20, (v + 0.20) / 2)
        for t, v in overlay.weight_ceilings.items()
    }
    half_caps = {c: min(1.0, (v + 1.0) / 2) for c, v in overlay.cluster_caps.items()}
    half_mult = (overlay.risk_asset_multiplier + 1.0) / 2
    half_floor = {t: v / 2 for t, v in overlay.tail_hedge_floor.items()}
    return RiskOverlay(
        weight_ceilings=half_ceilings,
        cluster_caps=half_caps,
        risk_asset_multiplier=half_mult,
        tail_hedge_floor=half_floor,
        severity_decision=f"[half] {overlay.severity_decision}",
        strength_applied=overlay.strength_applied * 0.5,
        lens_concerns=overlay.lens_concerns,
    )


def _solve_with_overlay(
    method: OptimizationMethod,
    returns: pd.DataFrame,
    candidates: CandidateSet,
    bucket_target: BucketTarget,
    overlay: RiskOverlay,
) -> WeightVector:
    """2차 optimization with overlay-derived constraints. infeasible 시 raise."""
    sector_mapper: dict[str, str] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        for t in tickers:
            sector_mapper[t] = bucket

    valid = [t for t in returns.columns if t in sector_mapper]
    returns = returns[valid].dropna(axis=0, how="any")

    adjusted_bucket = _shrink_bucket_by_multiplier(
        bucket_target, overlay.risk_asset_multiplier,
    )
    target_map = {
        "kr_equity": adjusted_bucket.kr_equity,
        "global_equity": adjusted_bucket.global_equity,
        "fx_commodity": adjusted_bucket.fx_commodity,
        "bond": adjusted_bucket.bond,
        "cash_mmf": adjusted_bucket.cash_mmf,
    }
    sector_lower = dict(target_map)
    sector_upper = dict(target_map)

    # HRP는 sector_constraints 미지원 → MIN_VARIANCE로 fallback (overlay 적용 시점에는
    # 항상 EF 기반으로 풀이; HRP는 1차 결과만 사용해도 OK).
    if method == OptimizationMethod.HRP:
        method = OptimizationMethod.MIN_VARIANCE

    bounds = _build_per_ticker_bounds(valid, overlay)
    # pypfopt의 weight_bounds는 전체 자산에 같은 범위. ticker별 bound는
    # add_constraint로 처리해야 함 → 단순화: 가장 엄격한 upper만 사용,
    # tail_hedge_floor는 lambda constraint로.

    global_upper = min(0.20, max(b[1] for b in bounds.values()))

    S = risk_models.sample_cov(returns)
    mu = expected_returns.mean_historical_return(returns, returns_data=True)

    ef = EfficientFrontier(mu, S, weight_bounds=(0, global_upper))
    ef.add_sector_constraints(sector_mapper, sector_lower, sector_upper)

    # Per-ticker upper constraints (overlay.weight_ceilings)
    asset_idx = {t: i for i, t in enumerate(ef.tickers)}
    for t, (_lower, upper) in bounds.items():
        if t not in asset_idx:
            continue
        if upper < global_upper - 1e-6:
            idx = asset_idx[t]
            ef.add_constraint(lambda w, i=idx, u=upper: w[i] <= u)
    # Per-ticker lower (tail_hedge_floor)
    for t, lower in overlay.tail_hedge_floor.items():
        if t in asset_idx and lower > 0:
            idx = asset_idx[t]
            ef.add_constraint(lambda w, i=idx, lo=lower: w[i] >= lo)

    # cluster_caps: 별도 group constraint
    if overlay.cluster_caps:
        # Phase 1에서는 cluster_caps 적용 skip (Stage 1 cluster id ↔ ticker
        # 매핑이 별도 state 필요). Phase 2에서 wire.
        pass

    if method == OptimizationMethod.MIN_VARIANCE:
        ef.min_volatility()
    elif method == OptimizationMethod.RISK_PARITY:
        ef.min_volatility()
    elif method == OptimizationMethod.BLACK_LITTERMAN:
        ef.max_sharpe()
    else:
        ef.max_sharpe()

    weights = {t: float(w) for t, w in ef.clean_weights().items() if w > 1e-4}
    total = sum(weights.values())
    if total <= 0:
        raise RuntimeError("Optimizer returned empty weights")
    weights = {t: w / total for t, w in weights.items()}

    if any(w > 0.20 + 1e-6 for w in weights.values()):
        raise RuntimeError("Optimizer with overlay still violates 20% cap")

    return WeightVector(
        method=method,
        weights=weights,
        rationale=(
            f"Stage 4 overlay applied "
            f"(strength={overlay.strength_applied:.2f}, "
            f"mult={overlay.risk_asset_multiplier:.2f}). "
            f"{overlay.severity_decision[:200]}"
        )[:500],
    )


def apply_risk_overlay(
    weight_vector_1: WeightVector,
    overlay: RiskOverlay,
    candidates: CandidateSet,
    returns: pd.DataFrame,
    bucket_target: BucketTarget,
    method: OptimizationMethod,
) -> WeightVector:
    """Apply Stage 4 overlay to Stage 3 1st result.

    Empty overlay → w1 그대로.
    Infeasible → half_strength → 1st fallback (overlay 무시 + log).
    """
    if overlay.is_empty():
        return weight_vector_1

    try:
        return _solve_with_overlay(
            method, returns, candidates, bucket_target, overlay,
        )
    except Exception as e:
        logger.warning(
            "Stage 4 overlay primary solve failed (%s) — trying half strength", e,
        )
        try:
            return _solve_with_overlay(
                method, returns, candidates, bucket_target,
                _half_strength(overlay),
            )
        except Exception as e2:
            logger.warning(
                "Stage 4 overlay half-strength also infeasible (%s) — "
                "returning Stage 3 1st result", e2,
            )
            # 1차 결과 그대로 반환 + rationale 갱신
            return weight_vector_1.model_copy(update={
                "rationale": (
                    f"[Stage 4 overlay infeasible — 1st result kept] "
                    f"{weight_vector_1.rationale[:400]}"
                )[:500],
            })
