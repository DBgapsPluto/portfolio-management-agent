"""Cash spillover — bucket-level conviction → redistribution to cash.

Phase 1 도입. Stage 2 macro bucket_target 을 micro evidence (alpha + ENB) 기반
conviction 으로 조정. conviction < threshold 면 비례 spillover, cash bucket cap
초과 시 high-conviction bucket 으로 재분배.
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
    raise NotImplementedError


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
    raise NotImplementedError
