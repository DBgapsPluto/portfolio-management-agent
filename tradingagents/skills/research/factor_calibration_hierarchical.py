"""Joint hierarchical β + μ optimization (Tier 2).

L(β, μ) = -Sharpe(β; train)
        + λ_global · ||β - prior||²
        + λ_family · Σ_(f,b) ||β_{f,b} - μ_{f, family(b)}||²
        + sign_penalty(β)

Hard-zero cells are clamped to 0 (not free variables). L-BFGS-B over
(free β entries + μ entries). free β = 96 - len(HARD_ZERO_CELLS) = 73.
μ = 12 factors × 5 families = 60. Total decision dim ≈ 133.
"""
from __future__ import annotations

import logging

import numpy as np
from scipy.optimize import minimize

from tradingagents.skills.research.factor_calibration import (
    BUCKET_FAMILIES, HARD_ZERO_CELLS, HistoricalSample,
    bucket_family, compute_sharpe,
    simulate_portfolio_returns_per_factor_aware,
)
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, FACTORS, INITIAL_BETA, SIGN_RESTRICTION,
)

logger = logging.getLogger(__name__)


def _sign_penalty(beta: dict[tuple[str, str], float]) -> float:
    pen = 0.0
    for key, expected in SIGN_RESTRICTION.items():
        val = beta.get(key, 0.0)
        if expected == "positive" and val < 0:
            pen += val**2 * 100
        elif expected == "negative" and val > 0:
            pen += val**2 * 100
    return pen


def hybrid_calibration_hierarchical(
    train: list[HistoricalSample],
    prior_beta: dict[tuple[str, str], float] | None = None,
    lambda_global: float = 2.0,
    lambda_family: float = 0.5,
    max_iter: int = 100,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float], float]:
    """Returns (calibrated_beta, calibrated_mu, in_sample_sharpe).

    calibrated_beta: full 96-entry dict (hard-zero cells = 0.0).
    calibrated_mu: {(factor, family): value} — 12×5 = 60 entries.
    """
    prior = prior_beta if prior_beta is not None else INITIAL_BETA
    free_beta_keys = sorted(set(prior.keys()) - HARD_ZERO_CELLS)
    # mu_keys: (factor, family_name) — one entry per factor × family
    mu_keys = sorted([(f, fam) for f in FACTORS for fam in BUCKET_FAMILIES])
    n_beta = len(free_beta_keys)

    # Build initial mu values: mean of prior β values for buckets in that family
    mu_init = []
    for (f, fam) in mu_keys:
        buckets_in_family = BUCKET_FAMILIES[fam]
        vals = [prior.get((f, b), 0.0) for b in buckets_in_family]
        mu_init.append(float(np.mean(vals)) if vals else 0.0)

    x0 = np.concatenate([
        np.array([prior[k] for k in free_beta_keys]),
        np.array(mu_init),
    ])
    bounds = [(-0.20, 0.20)] * n_beta + [(-0.15, 0.15)] * len(mu_keys)

    def _unpack(x: np.ndarray) -> tuple[dict, dict]:
        beta_free = {k: float(x[i]) for i, k in enumerate(free_beta_keys)}
        beta = {**beta_free, **{k: 0.0 for k in HARD_ZERO_CELLS}}
        mu = {k: float(x[n_beta + i]) for i, k in enumerate(mu_keys)}
        return beta, mu

    def objective(x: np.ndarray) -> float:
        beta, mu = _unpack(x)
        returns = simulate_portfolio_returns_per_factor_aware(train, beta)
        sharpe = compute_sharpe(returns)
        prior_pen = lambda_global * sum((beta[k] - prior[k])**2 for k in beta)
        fam_pen = 0.0
        for (f, b), v in beta.items():
            fam_pen += lambda_family * (v - mu[(f, bucket_family(b))]) ** 2
        return -sharpe + prior_pen + fam_pen + _sign_penalty(beta)

    result = minimize(objective, x0, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": max_iter})
    beta, mu = _unpack(result.x)
    final_sharpe = compute_sharpe(simulate_portfolio_returns_per_factor_aware(train, beta))
    return beta, mu, final_sharpe


def staggered_calibration(
    train_pre_2010: list[HistoricalSample],
    train_2010_plus: list[HistoricalSample],
    prior_beta: dict[tuple[str, str], float] | None = None,
    lambda_global: float = 2.0,
    lambda_family: float = 0.5,
    lambda_f11_multiplier: float = 2.0,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    """Two-stage staggered calibration for F11 (short-history factor).

    Phase A: main fit on full window (F11 column held at prior afterward).
    Phase B: F11 column sub-fit on 2010+ window with strong shrinkage.
    Returns (calibrated_beta, calibrated_mu).
    """
    prior = prior_beta if prior_beta is not None else INITIAL_BETA
    f11_keys = frozenset(k for k in prior if k[0] == "F11_earnings_revision")

    train_all = train_pre_2010 + train_2010_plus
    beta_main, mu_main, _ = hybrid_calibration_hierarchical(
        train_all, prior_beta=prior,
        lambda_global=lambda_global, lambda_family=lambda_family,
    )
    # Phase A treats F11 as fixed → restore F11 cells to prior
    for k in f11_keys:
        if k not in HARD_ZERO_CELLS:
            beta_main[k] = prior[k]

    # Phase B: sub-fit F11 free cells on 2010+ window, strong shrinkage
    lambda_f11 = max(lambda_f11_multiplier * lambda_global, 5.0)
    f11_free_keys = [k for k in sorted(f11_keys) if k not in HARD_ZERO_CELLS]
    if not f11_free_keys or not train_2010_plus:
        return beta_main, mu_main

    def _f11_objective(x: np.ndarray) -> float:
        beta_combined = dict(beta_main)
        for i, k in enumerate(f11_free_keys):
            beta_combined[k] = float(x[i])
        returns = simulate_portfolio_returns_per_factor_aware(train_2010_plus, beta_combined)
        sharpe = compute_sharpe(returns)
        pen = lambda_f11 * sum((beta_combined[k] - prior[k])**2 for k in f11_free_keys)
        return -sharpe + pen

    x0 = np.array([prior[k] for k in f11_free_keys])
    bounds = [(-0.10, 0.10)] * len(f11_free_keys)
    result = minimize(_f11_objective, x0, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": 50})
    for i, k in enumerate(f11_free_keys):
        beta_main[k] = float(result.x[i])
    return beta_main, mu_main


__all__ = ["hybrid_calibration_hierarchical", "staggered_calibration"]
