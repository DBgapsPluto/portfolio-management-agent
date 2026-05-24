"""Acceptance gate for PR2a INITIAL_BETA replacement (Critical 3 strict default).

5 conditions:
1. improvement: mean OOS > prior + 0.05 AND paired_t p < 0.20
2. overfit_guard: |mean_is - mean_oos| < 0.30
3. sign_respect: all calibrated β follow SIGN_RESTRICTION
4. saturation: fraction of |β| > 0.195 < 30%
5. fold_positive: ≥6 of 7 folds positive OOS Sharpe

Plus informational diagnostic:
- vintage_sanity (Critical 1)
- learning_sensitivity (M2)
- equi_weight_baseline (M3)
- saturated_fraction
- prior_stuck_fraction (M1)
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from scipy import stats

from tradingagents.skills.research.factor_to_bucket import (
    INITIAL_BETA, SIGN_RESTRICTION,
)

logger = logging.getLogger(__name__)


_SATURATION_THRESHOLD = 0.195  # |β| > 0.195 (bound 0.20)
_SATURATION_FRACTION_CAP = 0.30
_OVERFIT_GUARD_LIMIT = 0.30
_IMPROVEMENT_MARGIN = 0.05
_PAIRED_T_P_THRESHOLD = 0.20
_FOLD_POSITIVE_MIN = 6  # out of 7
_PRIOR_STUCK_THRESHOLD = 1e-3  # |β - prior| < threshold = stuck
_PRIOR_STUCK_FRACTION_WARN = 0.80


_SIGN_TOLERANCE = 1e-3  # grill-me #3 2026-05-24: numerical noise tolerance.
# β 의 가능 범위 [-0.20, 0.20] 의 0.5% — optimizer 가 거의 0 에 도달했으나
# strict `value ≤ 0` 에 의해 양수/음수 미세 차이로 reject 되는 edge case 흡수.


def _check_sign(key: tuple[str, str], value: float) -> bool:
    """SIGN_RESTRICTION 의 expected sign 위반 검출.

    `_SIGN_TOLERANCE` (1e-3) 범위 내 위반 은 noise 로 간주 — pass.
    """
    expected = SIGN_RESTRICTION.get(key, "either")
    if expected == "positive":
        return value >= -_SIGN_TOLERANCE
    if expected == "negative":
        return value <= _SIGN_TOLERANCE
    return True


def evaluate_acceptance(
    calibrated_beta: dict,
    calibrated_folds: list,
    prior_oos_per_fold: list[float],
    prior_oos_mean: float,
    equi_oos_mean: float,
    vintage_sanity: dict,
    learning_sensitivity: float,
) -> dict:
    """5-condition strict-default acceptance gate.

    Returns:
        {"pass": bool, "conditions": {...}, ..., "diagnostic": {...}}.
    """
    mean_is = float(np.mean([f.in_sample_sharpe for f in calibrated_folds]))
    mean_oos = float(np.mean([f.oos_sharpe for f in calibrated_folds]))
    calibrated_per_fold_oos = [f.oos_sharpe for f in calibrated_folds]

    paired_t_p = 1.0
    if len(prior_oos_per_fold) == len(calibrated_per_fold_oos):
        try:
            stat, paired_t_p = stats.ttest_rel(
                calibrated_per_fold_oos, prior_oos_per_fold,
                alternative="greater",
            )
            paired_t_p = float(paired_t_p)
        except Exception as e:
            logger.warning("paired t-test failed: %s", e)
            paired_t_p = 1.0

    # Condition 1: improvement (margin + paired-t)
    improvement = (
        (mean_oos > prior_oos_mean + _IMPROVEMENT_MARGIN)
        and (paired_t_p < _PAIRED_T_P_THRESHOLD)
    )

    # Condition 2: overfit guard
    overfit_guard = abs(mean_is - mean_oos) < _OVERFIT_GUARD_LIMIT

    # Condition 3: sign respect
    sign_respect = all(
        _check_sign(k, v) for k, v in calibrated_beta.items()
    )

    # Condition 4: saturation
    saturated_count = sum(
        1 for v in calibrated_beta.values() if abs(v) > _SATURATION_THRESHOLD
    )
    saturated_fraction = saturated_count / max(1, len(calibrated_beta))
    saturation = saturated_fraction < _SATURATION_FRACTION_CAP

    # Condition 5: fold positive
    fold_positive_count = sum(1 for s in calibrated_per_fold_oos if s > 0)
    fold_positive = fold_positive_count >= _FOLD_POSITIVE_MIN

    overall_pass = (
        improvement and overfit_guard and sign_respect
        and saturation and fold_positive
    )

    # M1 diagnostic: prior-stuck fraction
    stuck_count = sum(
        1 for k, v in calibrated_beta.items()
        if abs(v - INITIAL_BETA.get(k, 0.0)) < _PRIOR_STUCK_THRESHOLD
    )
    stuck_fraction = stuck_count / max(1, len(calibrated_beta))

    return {
        "pass": bool(overall_pass),
        "conditions": {
            "improvement": bool(improvement),
            "overfit_guard": bool(overfit_guard),
            "sign_respect": bool(sign_respect),
            "saturation": bool(saturation),
            "fold_positive": bool(fold_positive),
        },
        "mean_is_sharpe": mean_is,
        "mean_oos_sharpe": mean_oos,
        "prior_oos_sharpe": prior_oos_mean,
        "equi_weight_oos_sharpe": equi_oos_mean,
        "improvement_delta": mean_oos - prior_oos_mean,
        "paired_t_p": paired_t_p,
        "diagnostic": {
            "vintage_sanity_pass": vintage_sanity.get("pass", True),
            "vintage_sanity_avg_diff": vintage_sanity.get("avg_abs_diff", None),
            "vintage_sanity_skipped": vintage_sanity.get("skipped", True),
            "learning_sensitivity": learning_sensitivity,
            "learning_sensitivity_warning": learning_sensitivity < 0.01,
            "saturated_count": saturated_count,
            "saturated_fraction": saturated_fraction,
            "prior_stuck_count": stuck_count,
            "prior_stuck_fraction": stuck_fraction,
            "prior_stuck_warning": stuck_fraction > _PRIOR_STUCK_FRACTION_WARN,
            "fold_positive_count": fold_positive_count,
        },
    }
