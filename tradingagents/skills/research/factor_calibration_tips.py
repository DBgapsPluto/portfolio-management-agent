"""TIPS share scalar regression (Tier 2).

Smaller-dimensional regression for INITIAL_TIPS_BETA (12 entries).
No hierarchical/family structure (single scalar output: TIPS share within
the bond-equivalent bucket). Hard zero: F11/F12 × TIPS (earnings revision /
china credit have no link to TIPS preference).

Predicts tips_share_realized from factor z. Sample/param ≈ 133/10 = 13.3.
"""
from __future__ import annotations

from typing import Final

import numpy as np
from scipy.optimize import minimize

from tradingagents.skills.research.factor_calibration import HistoricalSample
from tradingagents.skills.research.factor_to_bucket import (
    INITIAL_TIPS_BASELINE, INITIAL_TIPS_BETA,
)

HARD_ZERO_TIPS: Final[frozenset[str]] = frozenset({
    "F11_earnings_revision",
    "F12_china_credit_impulse",
})


def hybrid_calibration_tips(
    train: list[HistoricalSample],
    prior_tips_beta: dict[str, float] | None = None,
    lambda_global: float = 2.0,
    max_iter: int = 50,
) -> tuple[dict[str, float], float]:
    """Returns (calibrated_tips_beta, in_sample_mse).

    Objective: MSE(predicted tips_share, realized) + λ·||β - prior||².
    Hard-zero factors (F11/F12) clamped to 0. Samples lacking
    tips_share_realized are skipped.
    """
    prior = prior_tips_beta if prior_tips_beta is not None else INITIAL_TIPS_BETA
    free_keys = sorted(set(prior.keys()) - HARD_ZERO_TIPS)

    def _unpack(x: np.ndarray) -> dict[str, float]:
        return {
            **{k: float(x[i]) for i, k in enumerate(free_keys)},
            **{k: 0.0 for k in HARD_ZERO_TIPS},
        }

    def objective(x: np.ndarray) -> float:
        beta = _unpack(x)
        pred, real = [], []
        for s in train:
            tips_realized = getattr(s, "tips_share_realized", None)
            if tips_realized is None:
                continue
            share = INITIAL_TIPS_BASELINE
            for f, b in beta.items():
                z = s.factor_z.get(f)
                if z is not None and not (isinstance(z, float) and np.isnan(z)):
                    share += b * z
            share = max(0.0, min(1.0, share))
            pred.append(share)
            real.append(tips_realized)
        if not pred:
            return 1e6
        mse = float(np.mean((np.array(pred) - np.array(real)) ** 2))
        prior_pen = lambda_global * sum((x[i] - prior[k])**2 for i, k in enumerate(free_keys))
        return mse + prior_pen

    x0 = np.array([prior[k] for k in free_keys])
    bounds = [(-0.30, 0.30)] * len(free_keys)
    result = minimize(objective, x0, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": max_iter})
    final = _unpack(result.x)
    return final, float(result.fun)


__all__ = ["hybrid_calibration_tips", "HARD_ZERO_TIPS"]
