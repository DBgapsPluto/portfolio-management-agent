"""
Phase 4a: Robust covariance estimation.

Ledoit-Wolf linear shrinkage covariance — replaces sample_cov / returns.cov()
across allocator, optimizers, NCO, overlay.

Why shrinkage: sample covariance is unbiased but high-variance in small-sample
regimes. Ledoit-Wolf 2004 shrinks toward identity target with closed-form δ.
PSD guaranteed.
"""
from __future__ import annotations

import pandas as pd
from pypfopt import risk_models


def compute_robust_cov(
    returns: pd.DataFrame,
    *,
    breakdown_out: dict | None = None,
) -> pd.DataFrame:
    """Ledoit-Wolf linear shrinkage covariance.

    Args:
        returns: T × N daily returns DataFrame (no NaN rows expected).
        breakdown_out: optional dict to record shrinkage_intensity (δ),
            n_obs, n_assets, estimator label for attribution.

    Returns:
        N × N shrinkage covariance DataFrame.

    Fallback: if estimator fails, returns sample_cov +
    breakdown_out["fallback_reason"]="shrinkage_failed: <Exception>".
    """
    n_obs, n_assets = returns.shape
    try:
        cs = risk_models.CovarianceShrinkage(returns, returns_data=True)
        shrunk = cs.ledoit_wolf()
        delta = float(cs.delta)
    except Exception as e:
        if breakdown_out is not None:
            breakdown_out["fallback_reason"] = f"shrinkage_failed: {type(e).__name__}"
            breakdown_out["n_obs"] = n_obs
            breakdown_out["n_assets"] = n_assets
        return risk_models.sample_cov(returns, returns_data=True)

    if breakdown_out is not None:
        breakdown_out["estimator"] = "ledoit_wolf"
        breakdown_out["shrinkage_intensity"] = delta
        breakdown_out["n_obs"] = n_obs
        breakdown_out["n_assets"] = n_assets

    return shrunk
