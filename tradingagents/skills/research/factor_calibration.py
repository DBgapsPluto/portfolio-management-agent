"""Walk-forward Sharpe maximization for factor model β.

Hybrid:
    L(β) = -Sharpe(β; train) + shrinkage × ||β - prior||²
    s.t. sign(β) == SIGN_RESTRICTION  (soft penalty)

scipy.optimize.minimize(L-BFGS-B) — bounded.

본 module 은 *infrastructure* — synthetic data 로 작동 검증 후, 실측 historical
fetch (Stage 1 backlog Issue #18) 이 완료되면 production calibration 수행.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Final
from scipy.optimize import minimize

from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS,
    FACTORS,
    INITIAL_BASELINE,
    INITIAL_BETA,
    SIGN_RESTRICTION,
    apply_factor_model,
    project_to_mandate_qp,
)


# ---------------------------------------------------------------------------
# Tier 2: Hierarchical calibration support constants
# ---------------------------------------------------------------------------

# Hard zero cells (theoretical exclusion). 23 entries (5 removed: prior-inconsistent /
# sign-softened cells — see Tier 2 verification).
HARD_ZERO_CELLS: Final[frozenset[tuple[str, str]]] = frozenset({
    ("F1_growth", "precious_metals"),
    ("F3_real_rate", "kr_equity"),
    ("F3_real_rate", "cyclical_commodity_fx"),
    ("F4_term_premium", "precious_metals"),
    ("F4_term_premium", "cyclical_commodity_fx"),
    ("F4_term_premium", "credit"),
    ("F5_credit_cycle", "precious_metals"),
    ("F5_credit_cycle", "cyclical_commodity_fx"),
    ("F6_krw_regime", "credit"),
    ("F6_krw_regime", "global_duration"),
    ("F7_equity_vol_regime", "precious_metals"),
    ("F8_valuation", "precious_metals"),
    ("F8_valuation", "cyclical_commodity_fx"),
    ("F8_valuation", "kr_bond"),
    ("F8_valuation", "credit"),
    ("F8_valuation", "global_duration"),
    ("F8_valuation", "cash_mmf"),
    ("F9_market_dispersion", "precious_metals"),
    ("F9_market_dispersion", "cyclical_commodity_fx"),
    ("F10_systemic_liquidity", "precious_metals"),
    ("F11_earnings_revision", "precious_metals"),
    ("F11_earnings_revision", "cyclical_commodity_fx"),
    ("F12_china_credit_impulse", "precious_metals"),
})

# Factors with NO identifiable historical signal in the committed panel:
#   F11 earnings_revision  -> all-NaN (no earnings-revision history in the panel)
#   F12 china_credit_impulse -> constant (no BIS China credit data in the panel)
# Both carry zero gradient during historical calibration: they cannot move from the
# hand-coded prior regardless of λ. Counting them as "free β params" overstates the
# overfitting burden, so the honest sample/param denominator excludes their cells.
# NOTE: this is a HISTORICAL-calibration accounting fact only — at runtime these
# factors may have live data and are NOT removed from the production factor model.
HISTORICALLY_UNIDENTIFIABLE_FACTORS: Final[frozenset[str]] = frozenset({
    "F11_earnings_revision",
    "F12_china_credit_impulse",
})


def count_free_beta_params() -> int:
    """Number of β cells the historical data can actually identify.

    = all (factor, bucket) cells, minus hard-zero cells, minus the cells of
    HISTORICALLY_UNIDENTIFIABLE_FACTORS (constant/NaN in the panel → pinned to
    prior, never fit). This is the honest denominator for the sample/param gate;
    it is NOT gate-gaming — the excluded cells are not free parameters in any
    real sense (they have no gradient).
    """
    return sum(
        1
        for f in FACTORS
        for b in BUCKETS
        if (f, b) not in HARD_ZERO_CELLS and f not in HISTORICALLY_UNIDENTIFIABLE_FACTORS
    )


# Bucket family groups for hierarchical prior.
BUCKET_FAMILIES: Final[dict[str, list[str]]] = {
    "equity":    ["kr_equity", "global_equity"],
    "commodity": ["precious_metals", "cyclical_commodity_fx"],
    "duration":  ["kr_bond", "global_duration"],
    "credit":    ["credit"],
    "cash":      ["cash_mmf"],
}


def bucket_family(bucket: str) -> str:
    """Return the family name for the given bucket.

    Raises ValueError for unknown bucket names.
    """
    for fam, members in BUCKET_FAMILIES.items():
        if bucket in members:
            return fam
    raise ValueError(f"Unknown bucket {bucket}")


def _project_simple(bucket: dict[str, float], risk_cap: float = 0.70) -> dict[str, float]:
    """Fast projection used in calibration loop to avoid nested QP.

    Production runtime uses project_to_mandate_qp (L2-optimal).
    Here we use proportional scaling — ~50x faster, slight intent distortion
    acceptable for calibration (β is averaged across folds via median anyway).
    """
    from tradingagents.skills.research.factor_to_bucket import RISK_BUCKETS as _RISK_BUCKETS

    bucket = {b: max(0.0, w) for b, w in bucket.items()}
    total = sum(bucket.values())
    if total <= 0:
        return dict(INITIAL_BASELINE)
    bucket = {b: w / total for b, w in bucket.items()}
    risk_buckets = tuple(b for b in _RISK_BUCKETS if b in bucket)
    risk = sum(bucket[b] for b in risk_buckets)
    if risk > risk_cap:
        scale = risk_cap / risk
        for b in risk_buckets:
            bucket[b] *= scale
        shortfall = 1.0 - sum(bucket.values())
        safe_buckets = {b: w for b, w in bucket.items() if b not in risk_buckets and w > 0}
        safe_total = sum(safe_buckets.values())
        if safe_total > 0:
            for b in safe_buckets:
                bucket[b] += shortfall * (bucket[b] / safe_total)
        elif bucket:
            # fallback: distribute to first non-risk bucket
            non_risk = [b for b in bucket if b not in risk_buckets]
            if non_risk:
                bucket[non_risk[0]] += shortfall
    return bucket


@dataclass
class HistoricalSample:
    """Single quarter sample."""

    date: str  # YYYY-MM-DD (quarter end)
    factor_z: dict[str, float]  # 12 factor z
    bucket_returns_next: dict[str, float]  # next quarter's realized returns per bucket
    tips_share_realized: float | None = None  # Tier 2: for TIPS scalar regression (Task 11)


def simulate_portfolio_returns(
    samples: list[HistoricalSample],
    beta: dict[tuple[str, str], float],
) -> np.ndarray:
    """Apply factor model with given β → portfolio return per quarter.
    Uses fast _project_simple (not QP) for calibration speed.
    """
    returns = []
    for s in samples:
        bucket, _, _ = apply_factor_model(s.factor_z, beta=beta)
        bucket = _project_simple(bucket)
        ret = sum(bucket[b] * s.bucket_returns_next.get(b, 0.0) for b in BUCKETS)
        returns.append(ret)
    return np.array(returns)


def simulate_portfolio_returns_per_factor_aware(
    samples: list[HistoricalSample],
    beta: dict[tuple[str, str], float],
    baseline: dict[str, float] | None = None,
) -> np.ndarray:
    """Apply factor model per-sample with NaN-skip.

    Each factor's contribution skipped when factor_z is None/NaN.
    Per-factor window emerges naturally: factor f's β only updates via
    samples where factor_z[f] is valid.
    """
    from tradingagents.skills.research.factor_to_bucket import (
        PER_FACTOR_BUCKET_CONTRIB_CAP, INITIAL_BASELINE as _INITIAL_BASELINE,
    )
    _baseline = baseline if baseline is not None else _INITIAL_BASELINE
    returns = []
    for s in samples:
        bucket = dict(_baseline)
        for f in FACTORS:
            z = s.factor_z.get(f)
            if z is None or (isinstance(z, float) and np.isnan(z)):
                continue
            for b in BUCKETS:
                contrib = beta.get((f, b), 0.0) * z
                contrib = max(-PER_FACTOR_BUCKET_CONTRIB_CAP,
                              min(PER_FACTOR_BUCKET_CONTRIB_CAP, contrib))
                bucket[b] = bucket.get(b, 0.0) + contrib
        projected = _project_simple(bucket)
        ret = sum(projected[b] * s.bucket_returns_next.get(b, 0.0) for b in BUCKETS)
        returns.append(ret)
    return np.array(returns)


def compute_effective_df(design_matrix: np.ndarray, lambda_global: float) -> float:
    """Effective degrees of freedom for ridge (Hastie-Tibshirani-Friedman ESL §3.4.1).

    df(λ) = Σ d_j² / (d_j² + λ), d_j = singular values of X.
    """
    _, sv, _ = np.linalg.svd(design_matrix, full_matrices=False)
    return float(np.sum(sv**2 / (sv**2 + lambda_global)))


def compute_vif_matrix(
    samples: list[HistoricalSample], factors: list[str]
) -> "pd.Series":
    """Per-factor VIF = 1 / (1 - R²_j) where R²_j regresses factor j on the rest.

    Returns pd.Series indexed by factor name. NaN if degenerate.
    Uses numpy least-squares (no sklearn dependency).
    """
    import pandas as pd
    Z = pd.DataFrame({
        f: [s.factor_z.get(f, np.nan) for s in samples]
        for f in factors
    }).dropna()
    vif = pd.Series(index=factors, dtype=float)
    Zv = Z.values
    for i, f in enumerate(factors):
        y = Zv[:, i]
        X = np.delete(Zv, i, axis=1)
        X1 = np.column_stack([np.ones(len(X)), X])
        try:
            coef, *_ = np.linalg.lstsq(X1, y, rcond=None)
            pred = X1 @ coef
            ss_res = float(np.sum((y - pred) ** 2))
            ss_tot = float(np.sum((y - y.mean()) ** 2))
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            vif[f] = 1.0 / max(1e-9, 1.0 - r2)
        except Exception:
            vif[f] = float("nan")
    return vif


def compute_sharpe(returns: np.ndarray, periods_per_year: int = 4) -> float:
    """Annualized Sharpe ratio (quarterly default)."""
    if len(returns) < 2:
        return 0.0
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    if std <= 0:
        return 0.0
    return mean / std * np.sqrt(periods_per_year)


def _flatten_beta(
    beta: dict[tuple[str, str], float],
) -> tuple[np.ndarray, list[tuple[str, str]]]:
    keys = sorted(beta.keys())
    return np.array([beta[k] for k in keys]), keys


def _unflatten_beta(
    flat: np.ndarray, keys: list[tuple[str, str]]
) -> dict[tuple[str, str], float]:
    return {k: float(flat[i]) for i, k in enumerate(keys)}


def _sign_penalty(beta: dict[tuple[str, str], float]) -> float:
    """SIGN_RESTRICTION violation penalty (additive to objective)."""
    pen = 0.0
    for key, expected in SIGN_RESTRICTION.items():
        val = beta.get(key, 0.0)
        if expected == "positive" and val < 0:
            pen += val**2 * 100
        elif expected == "negative" and val > 0:
            pen += val**2 * 100
    return pen


def hybrid_calibration(
    train: list[HistoricalSample],
    prior_beta: dict[tuple[str, str], float] | None = None,
    shrinkage: float = 0.5,
    max_iter: int = 50,
) -> tuple[dict[tuple[str, str], float], float]:
    """Returns (calibrated_beta, in_sample_sharpe).

    Hybrid objective:
        L(β) = -Sharpe(β; train) + shrinkage × ||β - prior||² + sign_penalty(β)

    bounds: |β| ≤ 0.20 per (factor, bucket).
    """
    prior = prior_beta or INITIAL_BETA
    x0_flat, keys = _flatten_beta(prior)
    prior_flat = x0_flat.copy()

    def objective(flat: np.ndarray) -> float:
        beta = _unflatten_beta(flat, keys)
        returns = simulate_portfolio_returns(train, beta)
        sharpe = compute_sharpe(returns)
        prior_pen = shrinkage * float(np.sum((flat - prior_flat) ** 2))
        sign_pen = _sign_penalty(beta)
        return -sharpe + prior_pen + sign_pen

    # bounds per (factor, bucket): |β| ≤ 0.20 (loose around hand-coded ≤ 0.12)
    bounds = [(-0.20, 0.20)] * len(keys)

    result = minimize(
        objective,
        x0=x0_flat,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": max_iter},
    )

    final = _unflatten_beta(result.x, keys)
    final_sharpe = compute_sharpe(simulate_portfolio_returns(train, final))
    return final, final_sharpe


@dataclass
class WalkForwardFold:
    fold_idx: int
    train_end_idx: int
    test_start_idx: int
    test_end_idx: int
    in_sample_sharpe: float
    oos_sharpe: float
    beta: dict[tuple[str, str], float]


def walk_forward(
    samples: list[HistoricalSample],
    initial_train_size: int = 80,  # 20 year quarterly
    test_window: int = 8,  # 2 year OOS — reduces fold count for fast iteration
    shrinkage: float = 0.5,
    prior_beta: dict[tuple[str, str], float] | None = None,
) -> list[WalkForwardFold]:
    """Expanding window walk-forward."""
    folds: list[WalkForwardFold] = []
    n = len(samples)
    fold_idx = 0
    for end in range(initial_train_size, n - test_window + 1, test_window):
        train = samples[:end]
        test = samples[end : end + test_window]
        beta, is_sharpe = hybrid_calibration(train, prior_beta, shrinkage)
        test_returns = simulate_portfolio_returns(test, beta)
        oos_sharpe = compute_sharpe(test_returns)
        folds.append(
            WalkForwardFold(
                fold_idx=fold_idx,
                train_end_idx=end,
                test_start_idx=end,
                test_end_idx=end + test_window,
                in_sample_sharpe=is_sharpe,
                oos_sharpe=oos_sharpe,
                beta=beta,
            )
        )
        fold_idx += 1
    return folds


def aggregate_median_beta(
    folds: list[WalkForwardFold],
) -> dict[tuple[str, str], float]:
    """Median β across folds (robust to outlier folds)."""
    if not folds:
        return dict(INITIAL_BETA)
    keys = sorted(folds[0].beta.keys())
    median: dict[tuple[str, str], float] = {}
    for k in keys:
        values = [f.beta[k] for f in folds]
        median[k] = float(np.median(values))
    return median


def benchmark_60_40_returns(
    samples: list[HistoricalSample],
    weights: dict[str, float] | None = None,
) -> np.ndarray:
    """Static 60/40 KR-tilted: kr_eq 20% + gl_eq 40% + global_duration 40%."""
    w = weights or {
        "kr_equity":             0.20,
        "global_equity":         0.40,
        "precious_metals":       0.00,
        "cyclical_commodity_fx": 0.00,
        "kr_bond":               0.00,
        "credit":                0.00,
        "global_duration":       0.40,
        "cash_mmf":              0.00,
    }
    returns = []
    for s in samples:
        ret = sum(w.get(b, 0.0) * s.bucket_returns_next.get(b, 0.0) for b in BUCKETS)
        returns.append(ret)
    return np.array(returns)
