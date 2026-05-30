"""Stage 4 RiskOverlay 를 Stage 3 optimizer 2 차 호출의 constraint 로 변환.

흐름:
  Stage 3 (1차) → WeightVector w1
  Stage 4       → RiskOverlay
  apply_risk_overlay (이 모듈):
    overlay 비면 → (w1, 'primary_success')
    overlay 차면 → drop_level 0 → 1 → 2 → 3 → 4 순으로 escalate, 처음 성공한
                   레벨의 outcome 반환. 모두 실패하면 (w1, 'fallback_to_1st').

drop_level 정의 (각 level 은 이전 level 의 완화를 누적 포함):
  0: full (cluster_caps + weight_ceilings + bucket equality + multiplier)
  1: cluster_caps 제거
  2: + weight_ceilings 제거
  3: + bucket equality → ±5%p band (Stage 3 D4 retry 패턴)
  4: + multiplier=1.0 (= 1차 결과 동일)

HRP method 는 sector_constraints 미지원 → MIN_VARIANCE 로 swap.
mandate (단일 cap 20%, sum=1.0) 는 overlay 적용 후에도 자동 보장.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from pypfopt import EfficientFrontier, expected_returns, risk_models
from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov

from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay
from tradingagents.schemas.technical import Cluster

logger = logging.getLogger(__name__)

_BUCKET_BAND = 0.05  # ±5%p (Stage 3 D4 retry 패턴과 동일)
SINGLE_ASSET_CAP_OVERLAY: float = 0.20

# 2026-05-26 backtest follow-up #2+#3:
# Stage 4 overlay 5-level all-infeasible 의 root cause 2 개를 함께 해결.
# (1) MIN_COV_OBS: portfolio_allocator.py 와 동일 60 (NaN-free row 최소).
#     신규 상장 ETF 가 후보에 포함되면 dropna(any) 후 obs 6 까지 떨어짐
#     (2024-08-14 사례). 짧은 history ticker 부터 점진 drop.
# (2) COV_RIDGE_LAMBDA: covariance 에 λ·trace·I 추가하여 non-PSD 회피
#     ("Eigenvalues did not converge" 해결). λ=1e-4 는 PyPortfolioOpt 의
#     fix_nonpositive_semidefinite 기본보다 약함, 결과 왜곡 < 0.1bp.
_MIN_COV_OBS_OVERLAY: int = 60
_COV_RIDGE_LAMBDA: float = 1e-4


def _filter_returns_for_cov(
    returns: pd.DataFrame, min_obs: int,
) -> tuple[pd.DataFrame, list[str]]:
    """NaN-drop 후 row 수가 min_obs 미만이면 짧은 history ticker 부터 drop.

    Returns (filtered_returns, excluded_ticker_list).
    """
    valid = list(returns.columns)
    filtered = returns[valid].dropna(axis=0, how="any")
    if len(filtered) >= min_obs:
        return filtered, []

    days_per_ticker = {
        t: int(returns[t].dropna().shape[0]) for t in valid
    }
    order = sorted(days_per_ticker, key=lambda t: days_per_ticker[t])
    excluded: list[str] = []
    while len(filtered) < min_obs and len(valid) > 5:
        drop = order.pop(0)
        valid.remove(drop)
        excluded.append(drop)
        filtered = returns[valid].dropna(axis=0, how="any")
    return filtered, excluded


def _ridge_cov(returns: pd.DataFrame, lam: float) -> pd.DataFrame:
    """sample_cov + λ·mean(diag)·I — PSD 보장 (numerical stability)."""
    S = compute_robust_cov(returns)
    ridge = lam * float(np.diag(S).mean())
    return S + ridge * np.eye(len(S))

# Stage 3 audit (2026-05-26, Task 4): 5 drop_level 의미 명시.
# 운영자가 attribution 만 봐도 어느 제약이 풀려서 통과했는지 알 수 있게.
OVERLAY_DROP_LEVELS: dict[int, str] = {
    0: "all_constraints",          # cluster_caps + weight_ceilings + bucket equality + multiplier
    1: "no_cluster_caps",          # cluster_caps 제거
    2: "no_weight_ceilings",       # + weight_ceilings 제거
    3: "bucket_band_relaxed",      # + bucket equality → ±5%p band
    4: "stage3_preserved",         # + multiplier=1.0 (= Stage 3 결과)
}

_OUTCOMES = [
    "primary_success", "relax_cluster", "relax_ceiling",
    "relax_band", "fallback_to_1st",
]


def _shrink_bucket_by_multiplier(
    bucket_target: BucketTarget, multiplier: float,
) -> BucketTarget:
    """위험자산 multiplier 적용 — 줄어든 만큼 bond + mmf 로 재정규화."""
    if multiplier >= 0.999:
        return bucket_target

    risk_orig = (
        bucket_target.kr_equity + bucket_target.global_equity
        + bucket_target.fx_commodity
    )
    safe_orig = bucket_target.bond + bucket_target.cash_mmf
    new_risk = risk_orig * multiplier
    shrinkage = risk_orig - new_risk

    if safe_orig > 0:
        bond_share = bucket_target.bond / safe_orig
        mmf_share = bucket_target.cash_mmf / safe_orig
        new_bond = bucket_target.bond + shrinkage * bond_share
        new_mmf = bucket_target.cash_mmf + shrinkage * mmf_share
    else:
        new_bond = bucket_target.bond + shrinkage * 0.6
        new_mmf = bucket_target.cash_mmf + shrinkage * 0.4

    risk_factor = new_risk / risk_orig if risk_orig > 0 else 0.0
    return BucketTarget(
        kr_equity=bucket_target.kr_equity * risk_factor,
        global_equity=bucket_target.global_equity * risk_factor,
        fx_commodity=bucket_target.fx_commodity * risk_factor,
        bond=new_bond, cash_mmf=new_mmf,
        rationale=(
            f"Stage 4 overlay shrink (×{multiplier:.2f}): "
            f"{bucket_target.rationale[:300]}"
        )[:500],
    )


def _solve_with_overlay(
    method: OptimizationMethod,
    returns: pd.DataFrame,
    candidates: CandidateSet,
    bucket_target: BucketTarget,
    overlay: RiskOverlay,
    clusters: list[Cluster],
    drop_level: int,
    overlay_attr: dict | None = None,
) -> WeightVector:
    """drop_level 별 overlay 구성으로 EF 풀이. infeasible 시 raise.

    drop_level 누적:
      0: cluster_caps + weight_ceilings + bucket equality + multiplier
      1: cluster_caps 제거
      2: + weight_ceilings 제거
      3: + bucket equality → ±5%p band
      4: + multiplier=1.0
    """
    sector_mapper: dict[str, str] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        for t in tickers:
            sector_mapper[t] = bucket

    valid = [t for t in returns.columns if t in sector_mapper]
    returns, excluded = _filter_returns_for_cov(
        returns[valid], _MIN_COV_OBS_OVERLAY,
    )
    if excluded:
        logger.warning(
            "Stage 4 overlay cov 표본 부족 — %d ETF cov 계산에서 제외: %s "
            "(남은 표본 %d row, level=%d)",
            len(excluded), excluded, len(returns), drop_level,
        )
        if overlay_attr is not None:
            # 동일 returns matrix 면 level 별 동일 결과 → 매 호출 overwrite 무해.
            overlay_attr["cov_excluded_tickers"] = list(excluded)
            overlay_attr["cov_final_obs"] = int(len(returns))

    # multiplier: level<=3 적용, level==4 면 1.0
    eff_multiplier = (
        overlay.risk_asset_multiplier if drop_level <= 3 else 1.0
    )
    adjusted_bucket = _shrink_bucket_by_multiplier(
        bucket_target, eff_multiplier,
    )
    target_map = {
        "kr_equity":     adjusted_bucket.kr_equity,
        "global_equity": adjusted_bucket.global_equity,
        "fx_commodity":  adjusted_bucket.fx_commodity,
        "bond":          adjusted_bucket.bond,
        "cash_mmf":      adjusted_bucket.cash_mmf,
    }
    # bucket: level<=2 equality, level>=3 ±band
    if drop_level <= 2:
        sector_lower = dict(target_map)
        sector_upper = dict(target_map)
    else:
        sector_lower = {k: max(0.0, v - _BUCKET_BAND) for k, v in target_map.items()}
        sector_upper = {k: min(1.0, v + _BUCKET_BAND) for k, v in target_map.items()}

    # 2026-05-26 backtest follow-up #2 잔여 (constraint conflict fix):
    # bucket 별 max achievable = (returns 에 있는 ticker 수) × SINGLE_ASSET_CAP
    # 계산. universe data 결함 / 신규 ETF / dropna 누락 등으로 bucket 의 max <
    # sector_lower 면 EF infeasible (예: cash_mmf 목표 37% 인데 returns 에 1 ticker
    # 만 → max 20%). sector_lower 를 max 로 자동 완화하고 attribution 에 기록.
    # 이게 4/5 historical 시점에서 overlay all-infeasible 의 root cause.
    bucket_ticker_count: dict[str, int] = {b: 0 for b in target_map}
    for t in returns.columns:
        b = sector_mapper.get(t)
        if b:
            bucket_ticker_count[b] += 1
    bucket_max_achievable = {
        b: n * SINGLE_ASSET_CAP_OVERLAY for b, n in bucket_ticker_count.items()
    }
    short_buckets: list[str] = []
    for b in list(sector_lower):
        max_ach = bucket_max_achievable[b]
        if sector_lower[b] > max_ach + 1e-6:
            short_buckets.append(
                f"{b}(target={sector_lower[b]:.3f},n_tickers={bucket_ticker_count[b]},"
                f"max={max_ach:.3f})"
            )
            # lower 를 max 로 완화 — 부족한 분은 다른 bucket 으로 흘러감
            sector_lower[b] = max_ach
            # upper 도 max 이하라면 lower 와 같게 (degenerate but feasible)
            if sector_upper[b] > max_ach + 1e-6:
                sector_upper[b] = max_ach
    if short_buckets:
        logger.warning(
            "Stage 4 overlay bucket 용량 부족 — %d bucket sector_lower 자동 완화 "
            "(level=%d): %s",
            len(short_buckets), drop_level, short_buckets,
        )
        if overlay_attr is not None:
            overlay_attr["bucket_capacity_shortfall"] = short_buckets

    # HRP fallback → MV (EF 기반)
    if method == OptimizationMethod.HRP:
        method = OptimizationMethod.MIN_VARIANCE

    # weight_ceilings: level<=1 적용, level>=2 제거
    ceilings = overlay.weight_ceilings if drop_level <= 1 else {}
    floors = overlay.tail_hedge_floor  # floor 는 항상 유지 (안전 신호)

    S = _ridge_cov(returns, _COV_RIDGE_LAMBDA)
    mu = expected_returns.mean_historical_return(returns, returns_data=True)

    ef = EfficientFrontier(mu, S, weight_bounds=(0, SINGLE_ASSET_CAP_OVERLAY))
    ef.add_sector_constraints(sector_mapper, sector_lower, sector_upper)

    asset_idx = {t: i for i, t in enumerate(ef.tickers)}

    # Per-ticker ceiling (level <= 1)
    for t, upper in ceilings.items():
        if t in asset_idx:
            idx = asset_idx[t]
            cap = min(SINGLE_ASSET_CAP_OVERLAY, upper)
            ef.add_constraint(lambda w, i=idx, u=cap: w[i] <= u)

    # Per-ticker floor (always)
    for t, lower in floors.items():
        if t in asset_idx and lower > 0:
            idx = asset_idx[t]
            ef.add_constraint(lambda w, i=idx, lo=lower: w[i] >= lo)

    # cluster_caps (level == 0 만)
    if drop_level == 0 and overlay.cluster_caps:
        for cluster in clusters:
            if cluster.cluster_id not in overlay.cluster_caps:
                continue
            cap = overlay.cluster_caps[cluster.cluster_id]
            indices = [asset_idx[t] for t in cluster.members if t in asset_idx]
            if len(indices) >= 2:
                ef.add_constraint(
                    lambda w, idxs=indices, c=cap: sum(w[i] for i in idxs) <= c
                )

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

    if any(w > SINGLE_ASSET_CAP_OVERLAY + 1e-6 for w in weights.values()):
        raise RuntimeError(
            f"Optimizer with overlay still violates {SINGLE_ASSET_CAP_OVERLAY*100:.0f}% cap"
        )

    return WeightVector(
        method=method,
        weights=weights,
        rationale=(
            f"Stage 4 overlay applied (drop_level={drop_level}, "
            f"strength={overlay.strength_applied:.2f}, "
            f"mult={eff_multiplier:.2f}). "
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
    clusters: list[Cluster] | None = None,
    attribution: dict | None = None,
) -> tuple[WeightVector, str]:
    """Stage 4 overlay 적용 → (WeightVector, outcome) tuple.

    outcome ∈ {primary_success, relax_cluster, relax_ceiling, relax_band,
    fallback_to_1st}. Empty overlay → (w1, primary_success).

    attribution (Stage 3 audit Task 4): 제공 시 다음 키 기록.
      - final_level: int — 성공한 drop_level (또는 None if all-fail)
      - final_level_label: str — OVERLAY_DROP_LEVELS[final_level]
      - infeasible_levels: list[int] — 실패한 level list
      - infeasible_errors: list[str] — 각 실패 사유
      - all_failed: bool — 모두 실패 시 True
      - dropped_constraints: list[str] — 성공 level 까지 누적 풀린 제약 list
    """
    if attribution is not None:
        attribution["overlay"] = {
            "final_level": None,
            "final_level_label": None,
            "infeasible_levels": [],
            "infeasible_errors": [],
            "all_failed": False,
            "dropped_constraints": [],
            # 2026-05-26 backtest follow-up #3 — short-history ticker drop 가시화.
            "cov_excluded_tickers": [],
            "cov_final_obs": None,
            # 2026-05-26 backtest follow-up #2 잔여 — bucket capacity shortfall 가시화.
            "bucket_capacity_shortfall": [],
        }
    overlay_attr = attribution["overlay"] if attribution is not None else None

    if overlay.is_empty():
        if overlay_attr is not None:
            overlay_attr["final_level"] = -1   # -1 = overlay empty (skip)
            overlay_attr["final_level_label"] = "overlay_empty"
        logger.info("Stage 4 overlay empty → 1차 결과 그대로 통과")
        return weight_vector_1, "primary_success"

    clusters = clusters or []
    last_err = None
    for level in range(5):
        try:
            wv = _solve_with_overlay(
                method, returns, candidates, bucket_target, overlay,
                clusters, drop_level=level, overlay_attr=overlay_attr,
            )
            logger.info(
                "Stage 4 overlay 성공: drop_level=%d (%s) → %s",
                level, OVERLAY_DROP_LEVELS[level], _OUTCOMES[level],
            )
            if overlay_attr is not None:
                overlay_attr["final_level"] = level
                overlay_attr["final_level_label"] = OVERLAY_DROP_LEVELS[level]
                # 성공 level 까지 누적 풀린 제약 (level 0 = 풀린 거 없음).
                overlay_attr["dropped_constraints"] = [
                    OVERLAY_DROP_LEVELS[i] for i in range(1, level + 1)
                ]
            return wv, _OUTCOMES[level]
        except Exception as e:
            last_err = e
            logger.warning(
                "Stage 4 overlay drop_level=%d (%s) infeasible: %s",
                level, OVERLAY_DROP_LEVELS[level], e,
            )
            if overlay_attr is not None:
                overlay_attr["infeasible_levels"].append(level)
                overlay_attr["infeasible_errors"].append(str(e)[:200])

    # 모든 level 실패 — 1 차 결과 보존
    logger.warning(
        "Stage 4 overlay all drop_levels infeasible → 1차 결과 보존. last err=%s",
        last_err,
    )
    if overlay_attr is not None:
        overlay_attr["all_failed"] = True
        overlay_attr["final_level_label"] = "all_infeasible_kept_stage3"
    return weight_vector_1.model_copy(update={
        "rationale": (
            f"[Stage 4 overlay infeasible — 1st result kept] "
            f"{weight_vector_1.rationale[:400]}"
        )[:500],
    }), "fallback_to_1st"
