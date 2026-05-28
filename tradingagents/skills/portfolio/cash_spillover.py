"""Cash spillover — bucket-level conviction → redistribution to cash.

Phase 1 도입. Stage 2 macro bucket_target 을 micro evidence (alpha + ENB) 기반
conviction 으로 조정.

3-step:
  1. 각 bucket weight 의 일부를 cash 로 spillover (spillover_ratio = 1 - conviction).
  2. cash_new > effective_cap (= max(0.40, macro cash)) 면 overflow 발생.
  3. overflow → conviction ≥ threshold 인 bucket 들로 conviction 가중 비례 재분배.
     high-conviction bucket 이 없으면 cash 가 cap 초과 허용 + WARNING.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.diversification import compute_enb

logger = logging.getLogger(__name__)


SPILLOVER_THRESHOLD_DEFAULT: float = 0.3
SPILLOVER_THRESHOLD_BY_BUCKET: dict[str, float] = {
    "fx_commodity": 0.15,
}
CASH_CAP_FOR_SPILLOVER_TARGET: float = 0.40
SPILLOVER_NUMERICAL_TOLERANCE: float = 1e-9


class ConvictionResult(BaseModel):
    bucket: str
    n_chosen: int
    mean_alpha: float
    enb: float
    threshold: float
    conviction: float
    spillover_ratio: float = Field(ge=0.0, le=1.0)


class SpilloverResult(BaseModel):
    adjusted_bucket_target: BucketTarget
    convictions: dict[str, ConvictionResult]
    cash_overflow_to_buckets: dict[str, float]
    total_spillover_to_cash: float
    cash_cap_triggered: bool
    thresholds: dict[str, float]


def _threshold_for(bucket: str) -> float:
    return SPILLOVER_THRESHOLD_BY_BUCKET.get(bucket, SPILLOVER_THRESHOLD_DEFAULT)


def compute_bucket_conviction(
    bucket: str,
    chosen: list[str],
    alpha_scores: dict[str, float],
    returns: pd.DataFrame,
) -> ConvictionResult:
    """Bucket conviction = (mean_alpha/threshold) × (ENB_equal_weight/√N)."""
    threshold = _threshold_for(bucket)

    if not chosen:
        return ConvictionResult(
            bucket=bucket, n_chosen=0, mean_alpha=0.0, enb=0.0,
            threshold=threshold, conviction=0.0, spillover_ratio=1.0,
        )

    available = [t for t in chosen if t in returns.columns]
    if not available:
        return ConvictionResult(
            bucket=bucket, n_chosen=0, mean_alpha=0.0, enb=0.0,
            threshold=threshold, conviction=0.0, spillover_ratio=1.0,
        )

    # mean alpha 는 chosen 전부에 대해 (returns 누락 종목도 포함)
    alphas = [alpha_scores.get(t, 0.0) for t in chosen]
    mean_alpha = float(np.mean(alphas))

    n = len(available)
    if n == 1:
        enb = 1.0
    else:
        sub_returns = returns[available].dropna(axis=0, how="any")
        if sub_returns.empty or len(sub_returns) < 2:
            enb = float(n)  # cov 계산 불가 → equal split fallback
        else:
            sigma = sub_returns.cov()
            equal_w = {t: 1.0 / n for t in available}
            enb = compute_enb(equal_w, sigma, method="minimum_torsion")

    conviction = (mean_alpha / threshold) * (enb / np.sqrt(n))
    spillover_ratio = max(0.0, min(1.0, 1.0 - conviction))

    return ConvictionResult(
        bucket=bucket, n_chosen=n, mean_alpha=mean_alpha, enb=float(enb),
        threshold=threshold, conviction=float(conviction),
        spillover_ratio=float(spillover_ratio),
    )


def adjust_bucket_targets(
    bucket_target: BucketTarget,
    bucket_chosen: dict[str, list[str]],
    alpha_scores_by_bucket: dict[str, dict[str, float]],
    returns: pd.DataFrame,
) -> SpilloverResult:
    """5 bucket conviction 계산 → 3-step redistribution.

    Step 1: bucket → cash_mmf 비례 spillover (cash_mmf 자체는 대상 아님)
    Step 2: effective_cap = max(0.40, bucket_target.cash_mmf) — macro 보존
    Step 3: overflow → high-conviction bucket conviction 가중 비례
    """
    # 입력 sanity
    total_in = (
        bucket_target.kr_equity + bucket_target.global_equity
        + bucket_target.fx_commodity + bucket_target.bond
        + bucket_target.cash_mmf
    )
    assert abs(total_in - 1.0) < SPILLOVER_NUMERICAL_TOLERANCE, (
        f"bucket_target sum {total_in} != 1.0"
    )

    bucket_names = ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf")

    # 1. 5 bucket conviction 계산
    convictions: dict[str, ConvictionResult] = {}
    for b in bucket_names:
        convictions[b] = compute_bucket_conviction(
            bucket=b,
            chosen=bucket_chosen.get(b, []),
            alpha_scores=alpha_scores_by_bucket.get(b, {}),
            returns=returns,
        )

    # 2. Step 1 — bucket → cash 비례 spillover (cash_mmf 제외)
    adjusted = {b: getattr(bucket_target, b) for b in bucket_names}
    spillover_amounts: dict[str, float] = {}
    for b in ("kr_equity", "global_equity", "fx_commodity", "bond"):
        amt = adjusted[b] * convictions[b].spillover_ratio
        spillover_amounts[b] = amt
        adjusted[b] -= amt
    cash_new = adjusted["cash_mmf"] + sum(spillover_amounts.values())

    # 3. Step 2 — effective_cap = max(0.40, macro cash) → macro 보존
    effective_cap = max(CASH_CAP_FOR_SPILLOVER_TARGET, bucket_target.cash_mmf)
    if cash_new <= effective_cap:
        adjusted["cash_mmf"] = cash_new
        overflow = 0.0
        cash_cap_triggered = False
    else:
        adjusted["cash_mmf"] = effective_cap
        overflow = cash_new - effective_cap
        cash_cap_triggered = True

    # 4. Step 3 — overflow → high-conviction bucket
    cash_overflow_to_buckets: dict[str, float] = {}
    if overflow > 0:
        high_conv = {
            b: convictions[b].conviction
            for b in ("kr_equity", "global_equity", "fx_commodity", "bond")
            if convictions[b].conviction >= convictions[b].threshold
        }
        if high_conv:
            total_weight = sum(high_conv.values())
            for b, c in high_conv.items():
                add = overflow * (c / total_weight)
                adjusted[b] += add
                cash_overflow_to_buckets[b] = add
        else:
            adjusted["cash_mmf"] += overflow
            logger.warning(
                "all buckets low-conviction; cash_mmf %.3f exceeds cap %.2f",
                adjusted["cash_mmf"], effective_cap,
            )

    # 5. 합 invariant 검증
    total_out = sum(adjusted.values())
    if abs(total_out - 1.0) > SPILLOVER_NUMERICAL_TOLERANCE:
        raise RuntimeError(
            f"spillover sum invariant broken: total_out={total_out}"
        )

    # 6. BucketTarget 새 instance (bond_tips_share 보존)
    adjusted_bt = BucketTarget(
        kr_equity=adjusted["kr_equity"],
        global_equity=adjusted["global_equity"],
        fx_commodity=adjusted["fx_commodity"],
        bond=adjusted["bond"],
        cash_mmf=adjusted["cash_mmf"],
        bond_tips_share=bucket_target.bond_tips_share,
        rationale=(
            f"{bucket_target.rationale or ''} | spillover {sum(spillover_amounts.values()):.3f} → cash"
        )[:300],
    )

    return SpilloverResult(
        adjusted_bucket_target=adjusted_bt,
        convictions=convictions,
        cash_overflow_to_buckets=cash_overflow_to_buckets,
        total_spillover_to_cash=sum(spillover_amounts.values()),
        cash_cap_triggered=cash_cap_triggered,
        thresholds={b: _threshold_for(b) for b in bucket_names},
    )
