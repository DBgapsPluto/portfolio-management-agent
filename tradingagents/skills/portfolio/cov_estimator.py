"""
Phase 4a: Robust covariance estimation.

Ledoit-Wolf linear shrinkage covariance — replaces sample_cov / returns.cov().
Live consumer: the Stage-5 validator fallback (min-variance re-optimization in
graph/conditional_logic.py). (The former NCO/optimizer consumers were removed
2026-06-03; the live allocator is deterministic AUM-weighted.)

Why shrinkage: sample covariance is unbiased but high-variance in small-sample
regimes. Ledoit-Wolf 2004 shrinks toward identity target with closed-form δ.
PSD guaranteed.

Phase 4d: QIS (Quadratic-Inverse Shrinkage) nonlinear estimator added as
default (Ledoit & Wolf 2020). Linear LW preserved via method="ledoit_wolf".
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pypfopt import risk_models


def compute_robust_cov(
    returns: pd.DataFrame,
    *,
    method: str = "qis",
    frequency: int = 252,
    breakdown_out: dict | None = None,
) -> pd.DataFrame:
    """Robust covariance estimator.

    Args:
        returns: T × N periodic returns DataFrame.
        method: "qis" (Ledoit-Wolf 2020 nonlinear, default) or "ledoit_wolf"
                (2004 linear).
        frequency: periods/year for annualization — ledoit_wolf 와 sample_cov
                폴백 양쪽에 관통 (폴백 미관통 시 주간 입력에서 252/52≈4.85×
                과대 Σ). qis 에서는 무시됨 — QIS 는 연율화 자체를 안 하며
                (raw-scale cov), 소비자(min-var 폴백)는 scale-invariant.
        breakdown_out: optional trace dict.

    Returns: N × N robust covariance DataFrame.

    Fallback: unknown method or estimator failure → sample_cov + fallback_reason
    + method_attempted.
    """
    n_obs, n_assets = returns.shape
    try:
        if method == "qis":
            shrunk_np, intensity = _qis_cov(returns.values)
            shrunk = pd.DataFrame(
                shrunk_np,
                index=returns.columns,
                columns=returns.columns,
            )
            delta = intensity
        elif method == "ledoit_wolf":
            cs = risk_models.CovarianceShrinkage(
                returns, returns_data=True, frequency=frequency)
            shrunk = cs.ledoit_wolf()
            delta = float(cs.delta)
        else:
            raise ValueError(f"unknown method: {method}")
    except Exception as e:
        if breakdown_out is not None:
            breakdown_out["fallback_reason"] = f"shrinkage_failed: {type(e).__name__}"
            breakdown_out["n_obs"] = n_obs
            breakdown_out["n_assets"] = n_assets
            breakdown_out["method_attempted"] = method
        return risk_models.sample_cov(returns, returns_data=True, frequency=frequency)

    if breakdown_out is not None:
        breakdown_out["estimator"] = method
        breakdown_out["shrinkage_intensity"] = float(delta)
        breakdown_out["n_obs"] = n_obs
        breakdown_out["n_assets"] = n_assets

    return shrunk


def _qis_cov(
    Y: np.ndarray,
    k: int = 1,
) -> tuple[np.ndarray, float]:
    """Quadratic-Inverse Shrinkage (Ledoit & Wolf 2020).

    Returns:
        cov_shrunk: N × N nonlinear-shrinkage covariance (symmetric).
        mean_intensity: mean(1 - shrunk_λ / sample_λ) over non-zero λ.
            QIS 는 per-eigenvalue 차등 shrinkage 라 단일 δ 가 없음.

    Reference: Ledoit & Wolf (2020) Annals of Statistics 48(5).
    """
    T, N = Y.shape
    Y = Y - Y.mean(axis=0, keepdims=True)
    n = T - k

    sample = (Y.T @ Y) / n

    lambdas, u = np.linalg.eigh(sample)
    lambdas = lambdas.real
    lambdas = np.maximum(lambdas, 0.0)

    c = N / n
    h = (min(c**2, 1.0 / c**2) ** 0.35) / N**0.35

    n_eff = min(N, n)
    lam_eff = lambdas[N - n_eff:]

    L = np.outer(lam_eff, np.ones(n_eff)) - np.outer(np.ones(n_eff), lam_eff)
    denom = L**2 + (h * lam_eff[:, None])**2
    denom = np.where(denom > 0, denom, 1.0)

    Hcomponent = L / denom
    Htilde = Hcomponent.mean(axis=1)

    fcomponent = (h * lam_eff[:, None]) / denom
    ftilde = (c / np.pi) * fcomponent.mean(axis=1)

    real_part = 1.0 - c - np.pi * c * lam_eff * Htilde
    imag_part = np.pi * c * lam_eff * ftilde
    d_star = lam_eff / (real_part**2 + imag_part**2 + 1e-30)

    d_full = np.zeros(N)
    d_full[N - n_eff:] = d_star

    cov_shrunk = u @ np.diag(d_full) @ u.T
    cov_shrunk = (cov_shrunk + cov_shrunk.T) / 2

    mask = lam_eff > 1e-12
    if mask.any():
        intensity = float(np.mean(1.0 - d_star[mask] / lam_eff[mask]))
    else:
        intensity = 0.0

    return cov_shrunk, intensity
