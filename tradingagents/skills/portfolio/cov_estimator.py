"""
Phase 4a: Robust covariance estimation.

Ledoit-Wolf linear shrinkage covariance — replaces sample_cov / returns.cov()
across allocator, optimizers, NCO, overlay.

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
    breakdown_out: dict | None = None,
) -> pd.DataFrame:
    """Robust covariance estimator.

    Args:
        returns: T × N daily returns DataFrame.
        method: "qis" (Ledoit-Wolf 2020 nonlinear, default) or "ledoit_wolf"
                (2004 linear).
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
            cs = risk_models.CovarianceShrinkage(returns, returns_data=True)
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
        return risk_models.sample_cov(returns, returns_data=True)

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


def compute_pairwise_selection_cov(
    returns: pd.DataFrame,
    *,
    min_periods: int = 30,
) -> pd.DataFrame:
    """Pairwise-complete cov for candidate selection (short-list ETFs)."""
    sigma = returns.cov(min_periods=min_periods)
    var = returns.var()
    diag = var.reindex(sigma.index).to_numpy()
    diag = np.where(np.isfinite(diag) & (diag > 0), diag, 1e-8)
    arr = sigma.to_numpy(dtype=float, copy=True)
    np.fill_diagonal(arr, diag)
    arr = np.nan_to_num(arr, nan=0.0)
    return pd.DataFrame(arr, index=sigma.index, columns=sigma.columns)


_FACTOR_PANEL_ATTRS: tuple[str, ...] = (
    "skip1m_mom_3m",
    "skip1m_mom_6m",
    "skip1m_mom_12m",
    "realized_vol_60d",
    "sharpe_60d",
    "log_aum",
)


def blend_cov_from_factor_panel_dict(
    S: pd.DataFrame,
    factor_panel: dict,
    *,
    blend: float = 0.25,
    breakdown_out: dict | None = None,
) -> pd.DataFrame:
    """Cross-sectional FactorPanel → low-rank covariance target (Stage 1 panel)."""
    if blend <= 0 or blend >= 1 or not factor_panel:
        return S
    tickers = [t for t in S.columns if t in factor_panel]
    if len(tickers) < 3:
        return S
    rows: list[list[float]] = []
    for t in tickers:
        fp = factor_panel[t]
        rows.append([
            float(getattr(fp, attr, 0.0) or 0.0)
            for attr in _FACTOR_PANEL_ATTRS
        ])
    X = np.array(rows, dtype=float)
    X = X - X.mean(axis=0, keepdims=True)
    cov_f = np.cov(X, rowvar=False)
    if cov_f.ndim == 0:
        cov_f = np.array([[float(cov_f)]])
    s_factor = X @ cov_f @ X.T
    s_factor = (s_factor + s_factor.T) / 2
    diag_s = np.diag(S.loc[tickers, tickers].to_numpy())
    diag_f = np.diag(s_factor)
    diag_f = np.where(diag_f > 1e-12, diag_f, 1e-12)
    scale = np.sqrt(np.maximum(diag_s, 1e-12) / diag_f)
    s_factor = (scale[:, None] * s_factor) * scale[None, :]
    s_blend = (1.0 - blend) * S.loc[tickers, tickers].to_numpy() + blend * s_factor
    s_blend = (s_blend + s_blend.T) / 2
    out = S.copy()
    out.loc[tickers, tickers] = s_blend
    if breakdown_out is not None:
        breakdown_out["factor_proxy_blend"] = float(blend)
        breakdown_out["factor_proxy_source"] = "cross_sectional_factor_panel"
        breakdown_out["factor_proxy_n_tickers"] = len(tickers)
    return out


def blend_cov_with_factor_proxy(
    S: pd.DataFrame,
    returns: pd.DataFrame,
    factor_panel: pd.DataFrame | dict | None,
    *,
    blend: float = 0.25,
    breakdown_out: dict | None = None,
) -> pd.DataFrame:
    """Blend sample cov toward factor-implied structure."""
    if factor_panel is None or blend <= 0 or blend >= 1:
        return S
    if isinstance(factor_panel, dict):
        return blend_cov_from_factor_panel_dict(
            S, factor_panel, blend=blend, breakdown_out=breakdown_out,
        )
    if not isinstance(factor_panel, pd.DataFrame):
        return S
    tickers = [t for t in S.columns if t in returns.columns]
    if not tickers:
        return S
    common_idx = returns.index.intersection(factor_panel.index)
    if len(common_idx) < max(30, len(tickers) + 5):
        if breakdown_out is not None:
            breakdown_out["factor_proxy_skipped"] = "insufficient_overlap"
        return S
    Y = returns.loc[common_idx, tickers].astype(float)
    F = factor_panel.loc[common_idx].select_dtypes(include=[np.number]).astype(float)
    if F.shape[1] == 0 or Y.shape[1] == 0:
        if breakdown_out is not None:
            breakdown_out["factor_proxy_skipped"] = "empty_factor_or_assets"
        return S
    F_arr = F.to_numpy()
    F_arr = F_arr - F_arr.mean(axis=0, keepdims=True)
    cov_f = np.cov(F_arr, rowvar=False)
    if cov_f.ndim == 0:
        cov_f = np.array([[float(cov_f)]])
    betas = []
    for col in Y.columns:
        y = Y[col].to_numpy()
        mask = np.isfinite(y)
        if mask.sum() < 20:
            betas.append(np.zeros(F.shape[1]))
            continue
        X = F_arr[mask]
        yy = y[mask]
        try:
            b, _, _, _ = np.linalg.lstsq(X, yy, rcond=None)
            betas.append(b)
        except np.linalg.LinAlgError:
            betas.append(np.zeros(F.shape[1]))
    B = np.array(betas)
    s_factor = B @ cov_f @ B.T
    s_factor = (s_factor + s_factor.T) / 2
    np.fill_diagonal(
        s_factor,
        np.maximum(np.diag(s_factor), np.diag(S.loc[tickers, tickers].to_numpy())),
    )
    s_blend = (1.0 - blend) * S.loc[tickers, tickers].to_numpy() + blend * s_factor
    s_blend = (s_blend + s_blend.T) / 2
    out = S.copy()
    out.loc[tickers, tickers] = s_blend
    if breakdown_out is not None:
        breakdown_out["factor_proxy_blend"] = float(blend)
        breakdown_out["factor_proxy_n_factors"] = int(F.shape[1])
        breakdown_out["factor_proxy_n_obs"] = int(len(common_idx))
    return out
