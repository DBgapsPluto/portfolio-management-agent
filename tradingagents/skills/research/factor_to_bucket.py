"""Factor → Bucket mapping + mandate projection.

Pipeline:
    factor_z (9 z-scores)
        ↓
    apply_factor_model: bucket = baseline + Σ_f β[f, b] × z[f]
        - Per-contribution cap: |β × z| ≤ 0.10 (PER_FACTOR_BUCKET_CONTRIB_CAP)
        ↓
    project_to_mandate_qp: L2-optimal projection
        - Solves: min ||w - bucket_target||²
        - Subject to: sum=1, 0≤w≤1, 위험자산 ≤ 0.70
        ↓
    BucketTarget (final)

Constraint priority (high → low):
    1. weights ≥ 0           (HARD — no shorting)
    2. sum = 1.0             (HARD — probability simplex)
    3. 위험자산 ≤ 0.70       (HARD — mandate §2.2)
    4. baseline L2 거리 최소화 (SOFT — intent preservation)

Note: 단일 ETF cap (≤0.20) 은 Stage 3 (portfolio_allocator) 영역.
      Cluster cap 은 Stage 4 (risk_judge overlay) 영역.
      Stage 2 의 projection 은 *bucket 수준* 제약 4 가지만 처리.

Edge cases:
    - QP optimizer failure → INITIAL_BASELINE fallback.
    - 모든 위험자산 weight < 0 → baseline fallback (factor intent 손상 — 매우 rare).
    - 모든 weight = 0 → INITIAL_BASELINE fallback.

Audit:
    apply_factor_model_with_safety() 가 diagnostics return — projection 의 *intervention magnitude*
    측정. ResearchDecision 의 narrative 에 *projection 작동 여부* 명시 가능.
"""
from __future__ import annotations

from typing import Any, Final, Literal

import numpy as np
from scipy.optimize import minimize


BUCKETS: Final[tuple[str, ...]] = (
    "kr_equity",
    "global_equity",
    "fx_commodity",
    "bond",
    "cash_mmf",
)

FACTORS: Final[tuple[str, ...]] = (
    "F1_growth",
    "F2_inflation",
    "F3_real_rate",
    "F4_term_premium",
    "F5_credit_cycle",
    "F6_krw_regime",
    "F7_equity_vol_regime",
    "F8_valuation",
    "F9_liquidity_regime",
)


INITIAL_BASELINE: Final[dict[str, float]] = {
    "kr_equity":     0.12,
    "global_equity": 0.20,
    "fx_commodity":  0.15,
    "bond":          0.33,
    "cash_mmf":      0.20,
}
# Σ = 1.0, 위험자산 = 0.47 (mandate 0.70 의 67%)

# Each factor row's β sums to 0 across buckets (adjustment preserves total)
# Spec section 5.4 hand-coded prior
INITIAL_BETA: Final[dict[tuple[str, str], float]] = {
    # F1 growth (+z = growth → +equity, -bond)
    ("F1_growth", "kr_equity"):     +0.04,
    ("F1_growth", "global_equity"): +0.06,
    ("F1_growth", "fx_commodity"):  +0.01,
    ("F1_growth", "bond"):          -0.08,
    ("F1_growth", "cash_mmf"):      -0.03,
    # F2 inflation
    ("F2_inflation", "kr_equity"):     -0.02,
    ("F2_inflation", "global_equity"): -0.03,
    ("F2_inflation", "fx_commodity"):  +0.07,
    ("F2_inflation", "bond"):          -0.05,
    ("F2_inflation", "cash_mmf"):      +0.03,
    # F3 real_rate (+z = high real → -long bond, +cash)
    ("F3_real_rate", "kr_equity"):     -0.02,
    ("F3_real_rate", "global_equity"): -0.03,
    ("F3_real_rate", "fx_commodity"):  -0.01,
    ("F3_real_rate", "bond"):          -0.05,
    ("F3_real_rate", "cash_mmf"):      +0.11,
    # F4 term_premium (+z = steep curve → +long bond, +equity)
    ("F4_term_premium", "kr_equity"):     +0.02,
    ("F4_term_premium", "global_equity"): +0.03,
    ("F4_term_premium", "fx_commodity"):  0.0,
    ("F4_term_premium", "bond"):          +0.02,
    ("F4_term_premium", "cash_mmf"):      -0.07,
    # F5 credit_cycle (+z = credit stress → -equity, -credit bond, +cash)
    ("F5_credit_cycle", "kr_equity"):     -0.05,
    ("F5_credit_cycle", "global_equity"): -0.06,
    ("F5_credit_cycle", "fx_commodity"):  +0.01,
    ("F5_credit_cycle", "bond"):          -0.02,
    ("F5_credit_cycle", "cash_mmf"):      +0.12,
    # F6 krw_regime (+z = weak KRW → +global, -kr)
    ("F6_krw_regime", "kr_equity"):     -0.05,
    ("F6_krw_regime", "global_equity"): +0.04,
    ("F6_krw_regime", "fx_commodity"):  +0.03,
    ("F6_krw_regime", "bond"):          -0.01,
    ("F6_krw_regime", "cash_mmf"):      -0.01,
    # F7 equity_vol_regime (+z = high vol → -risk, +cash)
    ("F7_equity_vol_regime", "kr_equity"):     -0.04,
    ("F7_equity_vol_regime", "global_equity"): -0.06,
    ("F7_equity_vol_regime", "fx_commodity"):  -0.02,
    ("F7_equity_vol_regime", "bond"):          +0.04,
    ("F7_equity_vol_regime", "cash_mmf"):      +0.08,
    # F8 valuation (+z = expensive (sp_pe 우세) → -equity)
    ("F8_valuation", "kr_equity"):     -0.03,
    ("F8_valuation", "global_equity"): -0.04,
    ("F8_valuation", "fx_commodity"):  +0.01,
    ("F8_valuation", "bond"):          +0.04,
    ("F8_valuation", "cash_mmf"):      +0.02,
    # F9 liquidity_regime (+z = liquidity stress → -risk, +cash)
    ("F9_liquidity_regime", "kr_equity"):     -0.03,
    ("F9_liquidity_regime", "global_equity"): -0.05,
    ("F9_liquidity_regime", "fx_commodity"):  -0.01,
    ("F9_liquidity_regime", "bond"):          +0.04,
    ("F9_liquidity_regime", "cash_mmf"):      +0.05,
}

# Bond TIPS share separate scalar regression (spec § 5.5)
INITIAL_TIPS_BASELINE: Final[float] = 0.30
INITIAL_TIPS_BETA: Final[dict[str, float]] = {
    "F1_growth":           +0.05,
    "F2_inflation":        +0.20,
    "F3_real_rate":        -0.10,
    "F4_term_premium":      0.0,
    "F5_credit_cycle":     -0.05,
    "F6_krw_regime":        0.0,
    "F7_equity_vol_regime": 0.0,
    "F8_valuation":         0.0,
    "F9_liquidity_regime": -0.03,
}

SignRestriction = Literal[
    "positive", "negative", "neutral", "positive_mild", "negative_mild"
]
SIGN_RESTRICTION: Final[dict[tuple[str, str], SignRestriction]] = {
    # F1 growth
    ("F1_growth", "kr_equity"):     "positive",
    ("F1_growth", "global_equity"): "positive",
    ("F1_growth", "bond"):          "negative",
    ("F1_growth", "cash_mmf"):      "negative",
    # F2 inflation
    ("F2_inflation", "fx_commodity"):  "positive",
    ("F2_inflation", "bond"):          "negative",
    # F3 real_rate
    ("F3_real_rate", "bond"):          "negative",
    ("F3_real_rate", "cash_mmf"):      "positive",
    # F5 credit_cycle
    ("F5_credit_cycle", "kr_equity"):     "negative",
    ("F5_credit_cycle", "global_equity"): "negative",
    ("F5_credit_cycle", "cash_mmf"):      "positive",
    # F7 equity_vol_regime
    ("F7_equity_vol_regime", "kr_equity"):     "negative",
    ("F7_equity_vol_regime", "global_equity"): "negative",
    ("F7_equity_vol_regime", "cash_mmf"):      "positive",
    # F8 valuation (+z = expensive → -equity)
    ("F8_valuation", "kr_equity"):     "negative",
    ("F8_valuation", "global_equity"): "negative",
}


PER_FACTOR_BUCKET_CONTRIB_CAP: Final[float] = 0.10
"""Single (factor, bucket) contribution 의 magnitude cap (±10pp).

이유: single factor 가 single bucket 을 dominate 못 하게 — diversification.
β × z 가 cap 을 초과하면 cap 으로 clip.
"""

RISK_BUCKETS: Final[tuple[str, ...]] = ("kr_equity", "global_equity", "fx_commodity")
"""Bucket level mandate (§2.2): 위험자산 sum ≤ 0.70."""

MANDATE_RISK_CAP: Final[float] = 0.70


# ---------------------------------------------------------------------------
# apply_factor_model — linear additive regression + per-contribution cap
# ---------------------------------------------------------------------------


def apply_factor_model(
    factor_z: dict[str, float],
    baseline: dict[str, float] | None = None,
    beta: dict[tuple[str, str], float] | None = None,
    tips_baseline: float | None = None,
    tips_beta: dict[str, float] | None = None,
) -> tuple[dict[str, float], float, dict[str, dict[str, float]]]:
    """factor z → bucket allocation (raw, pre-projection).

    Linear additive regression with per-(factor, bucket) contribution cap.

    Returns:
        bucket: ``{bucket_name: float}`` — sum *approximately* 1.0 (β rows
            sum to 0). After per-contribution capping the sum is no longer
            guaranteed exactly — projection step recovers sum=1.
        tips: bond TIPS share ∈ [0, 1].
        contributions: ``{factor: {bucket: capped_β·z}}`` — full audit trail.
    """
    baseline = baseline if baseline is not None else INITIAL_BASELINE
    beta = beta if beta is not None else INITIAL_BETA
    tips_baseline_v = (
        tips_baseline if tips_baseline is not None else INITIAL_TIPS_BASELINE
    )
    tips_beta_v = tips_beta if tips_beta is not None else INITIAL_TIPS_BETA

    bucket: dict[str, float] = dict(baseline)
    contributions: dict[str, dict[str, float]] = {}

    for f in FACTORS:
        z = float(factor_z.get(f, 0.0))
        contributions[f] = {}
        for b in BUCKETS:
            raw_contrib = beta.get((f, b), 0.0) * z
            contrib = max(
                -PER_FACTOR_BUCKET_CONTRIB_CAP,
                min(+PER_FACTOR_BUCKET_CONTRIB_CAP, raw_contrib),
            )
            bucket[b] = bucket.get(b, 0.0) + contrib
            contributions[f][b] = contrib

    tips = tips_baseline_v + sum(
        tips_beta_v.get(f, 0.0) * float(factor_z.get(f, 0.0)) for f in FACTORS
    )
    tips = max(0.0, min(1.0, tips))

    return bucket, tips, contributions


# ---------------------------------------------------------------------------
# project_to_mandate_qp — L2-optimal projection onto feasible polytope
# ---------------------------------------------------------------------------


def project_to_mandate_qp(
    bucket_target: dict[str, float],
    risk_cap: float = MANDATE_RISK_CAP,
) -> dict[str, float]:
    """QP-based projection: w* = argmin ||w - bucket_target||²

    Subject to:
      - Σ w = 1                       (probability simplex)
      - 0 ≤ w_b ≤ 1                   (no shorting)
      - Σ_{b ∈ risk} w_b ≤ risk_cap   (mandate)

    L2-optimal — factor model 의 intent (bucket 의 상대 거리) 최대한 보존.
    Optimizer failure 시 INITIAL_BASELINE fallback.
    """
    keys = list(bucket_target.keys())
    target = np.array([float(bucket_target[k]) for k in keys], dtype=float)
    risk_indices = [i for i, k in enumerate(keys) if k in RISK_BUCKETS]

    def objective(w: np.ndarray) -> float:
        return float(np.sum((w - target) ** 2))

    def objective_grad(w: np.ndarray) -> np.ndarray:
        return 2.0 * (w - target)

    def risk_jac(w: np.ndarray) -> np.ndarray:
        g = np.zeros_like(w)
        for i in risk_indices:
            g[i] = -1.0
        return g

    constraints = [
        {
            "type": "eq",
            "fun": lambda w: float(w.sum() - 1.0),
            "jac": lambda w: np.ones_like(w),
        },
        {
            "type": "ineq",
            "fun": lambda w: float(risk_cap - sum(w[i] for i in risk_indices)),
            "jac": risk_jac,
        },
    ]
    bounds = [(0.0, 1.0)] * len(keys)

    # Initial guess: clip & renormalise. If all-zero, fall back to uniform.
    x0 = np.clip(target, 0.0, 1.0)
    x0_sum = float(x0.sum())
    if x0_sum > 0:
        x0 = x0 / x0_sum
    else:
        x0 = np.ones_like(target) / len(target)

    try:
        result = minimize(
            objective,
            x0=x0,
            method="SLSQP",
            jac=objective_grad,
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 200, "ftol": 1e-9},
        )
        success = bool(result.success)
        w_raw = np.asarray(result.x, dtype=float)
    except Exception:  # pragma: no cover - defensive
        success = False
        w_raw = np.zeros_like(target)

    if not success:
        return dict(INITIAL_BASELINE)

    w = np.maximum(w_raw, 0.0)
    s = float(w.sum())
    if s <= 0.0:
        return dict(INITIAL_BASELINE)
    w = w / s
    return {k: float(w[i]) for i, k in enumerate(keys)}


# ---------------------------------------------------------------------------
# apply_factor_model_with_safety — regression + projection + diagnostics
# ---------------------------------------------------------------------------


def apply_factor_model_with_safety(
    factor_z: dict[str, float],
    **kwargs: Any,
) -> tuple[dict[str, float], float, dict[str, dict[str, float]], dict[str, object]]:
    """apply_factor_model + project_to_mandate_qp + diagnostics.

    Returns 4-tuple ``(bucket_projected, tips, contributions, diagnostics)``.

    Diagnostics keys:
        - pre_projection_risk_asset (float)
        - pre_projection_negatives (list[str])
        - pre_projection_sum (float)
        - mandate_violated_pre_projection (bool)
        - extreme_factor_active (bool)
        - projection_l2_distance (float)
        - projection_intervened (bool) — l2 > 0.01
    """
    bucket_raw, tips, contributions = apply_factor_model(factor_z, **kwargs)

    pre_risk = sum(bucket_raw.get(b, 0.0) for b in RISK_BUCKETS)
    pre_negatives = [b for b, w in bucket_raw.items() if w < -1e-9]
    pre_sum = float(sum(bucket_raw.values()))

    bucket_projected = project_to_mandate_qp(bucket_raw)

    keys = list(bucket_raw.keys())
    diff_vec = np.array(
        [bucket_projected[k] - bucket_raw[k] for k in keys], dtype=float
    )
    l2_dist = float(np.sqrt(np.sum(diff_vec**2)))

    extreme_active = any(abs(float(z)) >= 2.5 for z in factor_z.values())

    diagnostics: dict[str, object] = {
        "pre_projection_risk_asset": float(pre_risk),
        "pre_projection_negatives": pre_negatives,
        "pre_projection_sum": pre_sum,
        "mandate_violated_pre_projection": bool(pre_risk > MANDATE_RISK_CAP + 1e-9),
        "extreme_factor_active": bool(extreme_active),
        "projection_l2_distance": l2_dist,
        "projection_intervened": bool(l2_dist > 0.01),
    }

    return bucket_projected, tips, contributions, diagnostics
