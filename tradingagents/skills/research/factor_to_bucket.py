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

import logging
from typing import Any, Final, Literal

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


BUCKETS: Final[tuple[str, ...]] = (
    "kr_equity",
    "global_equity",
    "precious_metals",
    "cyclical_commodity_fx",
    "kr_bond",
    "credit",
    "global_duration",
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
    "F9_market_dispersion",
    # 2026-05-27 — F10 신규. F9 가 cross-sectional dispersion, F10 가 systemic.
    "F10_systemic_liquidity",
    # 2026-05-28 — F11/F12 신규 (Tier 0 완성).
    "F11_earnings_revision",
    "F12_china_credit_impulse",
)


RISK_BUCKETS: Final[tuple[str, ...]] = (
    "kr_equity",
    "global_equity",
    "precious_metals",
    "cyclical_commodity_fx",
)
"""Bucket level mandate (§2.2): 위험자산 sum ≤ 0.70."""

MANDATE_RISK_CAP: Final[float] = 0.70

INITIAL_BASELINE: Final[dict[str, float]] = {
    "kr_equity":             0.15,
    "global_equity":         0.20,
    "precious_metals":       0.08,
    "cyclical_commodity_fx": 0.14,
    "kr_bond":               0.15,
    "credit":                0.05,
    "global_duration":       0.13,
    "cash_mmf":              0.10,
}
# Σ위험 = 0.57, Σ안전 = 0.43, total = 1.0 (Option C — home bias, Gemini-validated).

# INITIAL_BETA — T1 2026-05-29: 8-bucket schema, 12×8 = 96 entries.
# Expert prior (row sum = 0 invariant enforced).
# Bucket rename: fx_commodity → cyclical_commodity_fx + precious_metals split;
#                bond → kr_bond + credit + global_duration split.
# F11/F12 새로 추가 (Tier 0 완성). All |β| ≤ 0.20, row sums = 0.
INITIAL_BETA: Final[dict[tuple[str, str], float]] = {
    # F1 growth (row sum = 0)
    ("F1_growth", "kr_equity"):             +0.05,
    ("F1_growth", "global_equity"):         +0.06,
    ("F1_growth", "precious_metals"):       -0.02,
    ("F1_growth", "cyclical_commodity_fx"): +0.03,
    ("F1_growth", "kr_bond"):               -0.04,
    ("F1_growth", "credit"):                +0.02,
    ("F1_growth", "global_duration"):       -0.05,
    ("F1_growth", "cash_mmf"):              -0.05,
    # F2 inflation (row sum = 0)
    ("F2_inflation", "kr_equity"):             -0.02,
    ("F2_inflation", "global_equity"):         -0.03,
    ("F2_inflation", "precious_metals"):       +0.04,
    ("F2_inflation", "cyclical_commodity_fx"): +0.05,
    ("F2_inflation", "kr_bond"):               -0.03,
    ("F2_inflation", "credit"):                -0.01,
    ("F2_inflation", "global_duration"):       -0.03,
    ("F2_inflation", "cash_mmf"):              +0.03,
    # F3 real_rate (row sum = 0)
    ("F3_real_rate", "kr_equity"):             -0.01,
    ("F3_real_rate", "global_equity"):         -0.02,
    ("F3_real_rate", "precious_metals"):       -0.05,
    ("F3_real_rate", "cyclical_commodity_fx"): -0.01,
    ("F3_real_rate", "kr_bond"):               -0.03,
    ("F3_real_rate", "credit"):                 0.00,
    ("F3_real_rate", "global_duration"):       -0.04,
    ("F3_real_rate", "cash_mmf"):              +0.16,
    # F4 term_premium (row sum = 0)
    ("F4_term_premium", "kr_equity"):             +0.02,
    ("F4_term_premium", "global_equity"):         +0.03,
    ("F4_term_premium", "precious_metals"):        0.00,
    ("F4_term_premium", "cyclical_commodity_fx"):  0.00,
    ("F4_term_premium", "kr_bond"):               +0.04,
    ("F4_term_premium", "credit"):                +0.01,
    ("F4_term_premium", "global_duration"):       +0.03,
    ("F4_term_premium", "cash_mmf"):              -0.13,
    # F5 credit_cycle (row sum = 0; precious 제거 — dash-for-cash 모순)
    ("F5_credit_cycle", "kr_equity"):             -0.05,
    ("F5_credit_cycle", "global_equity"):         -0.06,
    ("F5_credit_cycle", "precious_metals"):        0.00,
    ("F5_credit_cycle", "cyclical_commodity_fx"):  0.00,
    ("F5_credit_cycle", "kr_bond"):               +0.01,
    ("F5_credit_cycle", "credit"):                -0.06,
    ("F5_credit_cycle", "global_duration"):       +0.04,
    ("F5_credit_cycle", "cash_mmf"):              +0.12,
    # F6 krw_regime (row sum = 0)
    ("F6_krw_regime", "kr_equity"):             -0.05,
    ("F6_krw_regime", "global_equity"):         +0.05,
    ("F6_krw_regime", "precious_metals"):       +0.02,
    ("F6_krw_regime", "cyclical_commodity_fx"): +0.02,
    ("F6_krw_regime", "kr_bond"):               -0.01,
    ("F6_krw_regime", "credit"):                 0.00,
    ("F6_krw_regime", "global_duration"):       +0.01,
    ("F6_krw_regime", "cash_mmf"):              -0.04,
    # F7 equity_vol_regime (row sum = 0; gl_dur, precious 제거 — correlation breakdown)
    ("F7_equity_vol_regime", "kr_equity"):             -0.05,
    ("F7_equity_vol_regime", "global_equity"):         -0.06,
    ("F7_equity_vol_regime", "precious_metals"):        0.00,
    ("F7_equity_vol_regime", "cyclical_commodity_fx"): -0.03,
    ("F7_equity_vol_regime", "kr_bond"):               +0.02,
    ("F7_equity_vol_regime", "credit"):                -0.02,
    ("F7_equity_vol_regime", "global_duration"):       +0.04,
    ("F7_equity_vol_regime", "cash_mmf"):              +0.10,
    # F8 valuation (row sum = 0)
    ("F8_valuation", "kr_equity"):             -0.04,
    ("F8_valuation", "global_equity"):         -0.05,
    ("F8_valuation", "precious_metals"):       +0.01,
    ("F8_valuation", "cyclical_commodity_fx"): +0.01,
    ("F8_valuation", "kr_bond"):               +0.02,
    ("F8_valuation", "credit"):                +0.01,
    ("F8_valuation", "global_duration"):       +0.02,
    ("F8_valuation", "cash_mmf"):              +0.02,
    # F9 market_dispersion (row sum = 0)
    ("F9_market_dispersion", "kr_equity"):             -0.04,
    ("F9_market_dispersion", "global_equity"):         -0.05,
    ("F9_market_dispersion", "precious_metals"):       -0.02,
    ("F9_market_dispersion", "cyclical_commodity_fx"): -0.02,
    ("F9_market_dispersion", "kr_bond"):               +0.03,
    ("F9_market_dispersion", "credit"):                -0.02,
    ("F9_market_dispersion", "global_duration"):       +0.02,
    ("F9_market_dispersion", "cash_mmf"):              +0.10,
    # F10 systemic_liquidity (row sum = 0; +z = tight FCI = stress → risk-off)
    ("F10_systemic_liquidity", "kr_equity"):             -0.06,
    ("F10_systemic_liquidity", "global_equity"):         -0.07,
    ("F10_systemic_liquidity", "precious_metals"):       +0.02,
    ("F10_systemic_liquidity", "cyclical_commodity_fx"): -0.02,
    ("F10_systemic_liquidity", "kr_bond"):               +0.04,
    ("F10_systemic_liquidity", "credit"):                -0.04,
    ("F10_systemic_liquidity", "global_duration"):       +0.04,
    ("F10_systemic_liquidity", "cash_mmf"):              +0.09,
    # F11 earnings_revision (row sum = 0; 2026-05-28 신규)
    ("F11_earnings_revision", "kr_equity"):             +0.05,
    ("F11_earnings_revision", "global_equity"):         +0.05,
    ("F11_earnings_revision", "precious_metals"):       -0.01,
    ("F11_earnings_revision", "cyclical_commodity_fx"): +0.01,
    ("F11_earnings_revision", "kr_bond"):               -0.02,
    ("F11_earnings_revision", "credit"):                +0.02,
    ("F11_earnings_revision", "global_duration"):       -0.04,
    ("F11_earnings_revision", "cash_mmf"):              -0.06,
    # F12 china_credit_impulse (row sum = 0; 2026-05-28 신규)
    ("F12_china_credit_impulse", "kr_equity"):             +0.04,
    ("F12_china_credit_impulse", "global_equity"):         +0.04,
    ("F12_china_credit_impulse", "precious_metals"):        0.00,
    ("F12_china_credit_impulse", "cyclical_commodity_fx"): +0.04,
    ("F12_china_credit_impulse", "kr_bond"):               -0.02,
    ("F12_china_credit_impulse", "credit"):                +0.02,
    ("F12_china_credit_impulse", "global_duration"):       -0.04,
    ("F12_china_credit_impulse", "cash_mmf"):              -0.08,
}

# Bond TIPS share separate scalar regression (spec § 5.5)
INITIAL_TIPS_BASELINE: Final[float] = 0.30
INITIAL_TIPS_BETA: Final[dict[str, float]] = {
    "F1_growth":               +0.05,
    "F2_inflation":            +0.20,
    "F3_real_rate":            -0.10,
    "F4_term_premium":          0.00,
    "F5_credit_cycle":         -0.05,
    "F6_krw_regime":            0.00,
    "F7_equity_vol_regime":     0.00,
    "F8_valuation":             0.00,
    "F9_market_dispersion":    -0.03,
    "F10_systemic_liquidity":  +0.05,  # systemic stress 시 TIPS preference 약간 ↑
    "F11_earnings_revision":    0.00,
    "F12_china_credit_impulse": 0.00,
}

SignRestriction = Literal[
    "positive", "negative", "neutral", "positive_mild", "negative_mild"
]
SIGN_RESTRICTION: Final[dict[tuple[str, str], SignRestriction]] = {
    # F1 growth
    ("F1_growth", "kr_equity"):       "positive",
    ("F1_growth", "global_equity"):   "positive",
    ("F1_growth", "credit"):          "positive",
    ("F1_growth", "kr_bond"):         "negative",
    ("F1_growth", "global_duration"): "negative",
    ("F1_growth", "cash_mmf"):        "negative",
    # F2 inflation
    ("F2_inflation", "precious_metals"):       "positive",
    ("F2_inflation", "cyclical_commodity_fx"): "positive",
    ("F2_inflation", "kr_bond"):               "negative",
    ("F2_inflation", "global_duration"):       "negative",
    # F3 real_rate
    ("F3_real_rate", "precious_metals"):  "negative",
    ("F3_real_rate", "kr_bond"):          "negative",
    ("F3_real_rate", "global_duration"):  "negative",
    ("F3_real_rate", "cash_mmf"):         "positive",
    # F4 term_premium
    ("F4_term_premium", "kr_bond"):         "positive",
    ("F4_term_premium", "global_duration"): "positive",
    ("F4_term_premium", "cash_mmf"):        "negative",
    # F5 credit_cycle (precious 제거 — dash-for-cash 모순)
    ("F5_credit_cycle", "kr_equity"):     "negative",
    ("F5_credit_cycle", "global_equity"): "negative",
    ("F5_credit_cycle", "credit"):        "negative",
    ("F5_credit_cycle", "cash_mmf"):      "positive",
    # F6 krw_regime
    ("F6_krw_regime", "kr_equity"):     "negative",
    ("F6_krw_regime", "global_equity"): "positive",
    # F7 equity_vol_regime (gl_dur, precious 제거 — correlation breakdown)
    ("F7_equity_vol_regime", "kr_equity"):     "negative",
    ("F7_equity_vol_regime", "global_equity"): "negative",
    ("F7_equity_vol_regime", "cash_mmf"):      "positive",
    # F8 valuation (+z = expensive → -equity)
    ("F8_valuation", "kr_equity"):     "negative",
    ("F8_valuation", "global_equity"): "negative",
    # F9 market_dispersion
    ("F9_market_dispersion", "kr_equity"):     "negative",
    ("F9_market_dispersion", "global_equity"): "negative",
    ("F9_market_dispersion", "cash_mmf"):      "positive",
    # F10 systemic_liquidity (+z = tight FCI = systemic stress)
    ("F10_systemic_liquidity", "kr_equity"):              "negative",
    ("F10_systemic_liquidity", "global_equity"):          "negative",
    ("F10_systemic_liquidity", "credit"):                 "negative",
    ("F10_systemic_liquidity", "cyclical_commodity_fx"):  "negative",
    ("F10_systemic_liquidity", "kr_bond"):                "positive",
    ("F10_systemic_liquidity", "global_duration"):        "positive",
    ("F10_systemic_liquidity", "cash_mmf"):               "positive",
    # F11 earnings_revision
    ("F11_earnings_revision", "kr_equity"):     "positive",
    ("F11_earnings_revision", "global_equity"): "positive",
    ("F11_earnings_revision", "cash_mmf"):      "negative",
    # F12 china_credit_impulse
    ("F12_china_credit_impulse", "kr_equity"):              "positive",
    ("F12_china_credit_impulse", "cyclical_commodity_fx"):  "positive",
}


PER_FACTOR_BUCKET_CONTRIB_CAP: Final[float] = 0.10
"""Single (factor, bucket) contribution 의 magnitude cap (±10pp).

이유: single factor 가 single bucket 을 dominate 못 하게 — diversification.
β × z 가 cap 을 초과하면 cap 으로 clip.
"""


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

    fail_msg: str | None = None
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
        if not success:
            fail_msg = f"SLSQP non-success: status={result.status}, message={result.message}"
        w_raw = np.asarray(result.x, dtype=float)
    except Exception as e:  # pragma: no cover - defensive
        success = False
        fail_msg = f"SLSQP raised: {e}"
        w_raw = np.zeros_like(target)

    if not success:
        # Stage 2 audit (Task 2): silent → logger.warning. fallback 발동 visible.
        logger.warning(
            "project_to_mandate_qp: optimizer failed → INITIAL_BASELINE fallback (%s). "
            "factor intent 손상 — narrative 에 명시 권장. target=%s",
            fail_msg, bucket_target,
        )
        return dict(INITIAL_BASELINE)

    w = np.maximum(w_raw, 0.0)
    s = float(w.sum())
    if s <= 0.0:
        logger.warning(
            "project_to_mandate_qp: w.sum=0 post-clip → INITIAL_BASELINE fallback. "
            "target=%s w_raw=%s", bucket_target, w_raw.tolist(),
        )
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

    Diagnostics keys (Stage 2 audit Task 2 — 외부 노출용 의미 명시):
      - pre_projection_risk_asset (float): projection 전 위험자산 합. 0.70 초과면 mandate 위반.
      - pre_projection_negatives (list[str]): projection 전 weight<0 bucket — factor intent 가
        baseline 을 넘어 음수 영역까지 보내려 함. projection 으로 0 으로 clip 됨.
      - pre_projection_sum (float): projection 전 sum. β rows sum to 0 + cap 으로 약간 ≠ 1.0
        가능. projection 이 sum=1 회복.
      - mandate_violated_pre_projection (bool): pre_risk > 0.70 + ε. projection 강제 발동.
      - extreme_factor_active (bool): 어느 factor 의 |z| ≥ 2.5. tail event 가능성 — 운영자
        리뷰 권장.
      - projection_l2_distance (float): bucket_projected vs bucket_raw 의 L2 거리.
        0.01 미만 = projection 거의 무동작, 큰 값 = factor intent 가 mandate 와 충돌.
      - projection_intervened (bool): l2_dist > 0.01.
      - cap_hits (int): per-factor-bucket β·z 가 ±0.10 cap 에 닿은 (factor, bucket) 페어 수.
        많을수록 single factor 가 single bucket 을 dominate 하려 한 정도 — diversification
        보호 발동 빈도.
      - cap_hits_detail (list[tuple[str, str, float]]): 각 cap hit 의 (factor, bucket,
        capped_value) — debugging.
    """
    bucket_raw, tips, contributions = apply_factor_model(factor_z, **kwargs)

    pre_risk = sum(bucket_raw.get(b, 0.0) for b in RISK_BUCKETS)
    pre_negatives = [b for b, w in bucket_raw.items() if w < -1e-9]
    pre_sum = float(sum(bucket_raw.values()))

    # Stage 2 audit (Task 2): cap_hits — 어느 (factor, bucket) 페어가 cap 에 닿았나.
    # contributions[f][b] 가 정확히 ±PER_FACTOR_BUCKET_CONTRIB_CAP 면 cap 발동.
    cap_eps = 1e-12
    cap_hits_detail: list[tuple[str, str, float]] = []
    for f, fmap in contributions.items():
        for b, c in fmap.items():
            if abs(abs(c) - PER_FACTOR_BUCKET_CONTRIB_CAP) < cap_eps:
                cap_hits_detail.append((f, b, c))

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
        "cap_hits": len(cap_hits_detail),
        "cap_hits_detail": cap_hits_detail,
    }

    return bucket_projected, tips, contributions, diagnostics
