"""Unit tests for factor → bucket additive regression + safety diagnostics.

Tests in this file cover:
  - apply_factor_model: linear additive regression with per-contribution cap
  - apply_factor_model_with_safety: regression + QP projection + diagnostics
  - INITIAL_BETA / INITIAL_BASELINE invariants
"""
from __future__ import annotations

import math

import pytest

from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS,
    FACTORS,
    INITIAL_BASELINE,
    INITIAL_BETA,
    INITIAL_TIPS_BASELINE,
    INITIAL_TIPS_BETA,
    PER_FACTOR_BUCKET_CONTRIB_CAP,
    apply_factor_model,
    apply_factor_model_with_safety,
)


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


def test_initial_beta_each_factor_sums_to_zero():
    """Each factor row 의 β sum 이 0 (adjustment preserves total = 1)."""
    for f in FACTORS:
        row_sum = sum(INITIAL_BETA.get((f, b), 0.0) for b in BUCKETS)
        assert abs(row_sum) < 1e-6, f"{f}: row sum {row_sum} != 0"


def test_initial_baseline_sums_to_one():
    assert abs(sum(INITIAL_BASELINE.values()) - 1.0) < 1e-6


def test_initial_baseline_satisfies_mandate():
    risk = (
        INITIAL_BASELINE["kr_equity"]
        + INITIAL_BASELINE["global_equity"]
        + INITIAL_BASELINE["fx_commodity"]
    )
    assert risk <= 0.70


# ---------------------------------------------------------------------------
# apply_factor_model — basic linear additive
# ---------------------------------------------------------------------------


def _zero_z() -> dict[str, float]:
    return {f: 0.0 for f in FACTORS}


def test_apply_factor_model_baseline_returns_baseline():
    """All z = 0 → bucket = baseline exactly."""
    bucket, tips, contributions = apply_factor_model(_zero_z())
    for b in BUCKETS:
        assert math.isclose(bucket[b], INITIAL_BASELINE[b], abs_tol=1e-9)
    # contributions 모두 0
    for f in FACTORS:
        for b in BUCKETS:
            assert math.isclose(contributions[f][b], 0.0, abs_tol=1e-12)


def test_apply_factor_model_growth_lifts_equity():
    """F1 = +1.5 → equity ↑, bond ↓ (consistent with positive growth β)."""
    z = _zero_z()
    z["F1_growth"] = 1.5
    bucket, _, _ = apply_factor_model(z)
    assert bucket["kr_equity"] > INITIAL_BASELINE["kr_equity"]
    assert bucket["global_equity"] > INITIAL_BASELINE["global_equity"]
    assert bucket["bond"] < INITIAL_BASELINE["bond"]


def test_apply_factor_model_preserves_sum_when_no_capping():
    """All |z| ≤ 1 with no individual β·z exceeding the cap → bucket sum = 1.0.

    Note: per-contribution cap (=0.10) 가 trigger 되지 않는 한 row sum = 0 invariant
    이 그대로 적용 → bucket sum = baseline sum = 1.0. INITIAL_BETA 에서 |β| > 0.10
    인 entry (F3 cash_mmf=+0.11, F5 cash_mmf=+0.12, F5 credit_cycle cash_mmf=+0.12)
    이므로 z=1 에서도 cap 이 trigger 됨. 따라서 capping 이 안 발생하는 작은 z 로 테스트.
    """
    z = {f: 0.5 for f in FACTORS}  # |β·z| ≤ 0.06 < 0.10 cap
    bucket, _, _ = apply_factor_model(z)
    s = sum(bucket.values())
    assert abs(s - 1.0) < 1e-6, f"sum={s}"


def test_apply_factor_model_sum_drift_bounded_under_capping():
    """All z = 1 → cap 이 일부 contribution 을 clip → sum drift 발생, but 작아야."""
    z = {f: 1.0 for f in FACTORS}
    bucket, _, _ = apply_factor_model(z)
    s = sum(bucket.values())
    # 알려진 clipping: F3 cash_mmf(+0.11→+0.10), F5 cash_mmf(+0.12→+0.10) = -0.03
    # → sum ≈ 0.97. projection 단계에서 sum=1 로 복원.
    assert 0.90 < s < 1.10, f"sum drift too large: {s}"


def test_apply_factor_model_contributions_audit():
    """F1 = +1, 다른 z = 0 → contributions[F1_growth] 가 raw β 값."""
    z = _zero_z()
    z["F1_growth"] = 1.0
    _, _, contributions = apply_factor_model(z)
    assert math.isclose(contributions["F1_growth"]["kr_equity"], +0.04, abs_tol=1e-9)
    assert math.isclose(contributions["F1_growth"]["bond"], -0.08, abs_tol=1e-9)
    # 다른 factor 의 contribution 은 0
    for f in FACTORS:
        if f == "F1_growth":
            continue
        for b in BUCKETS:
            assert math.isclose(contributions[f][b], 0.0, abs_tol=1e-12)


def test_apply_factor_model_tips_share():
    """All z = 0 → tips = INITIAL_TIPS_BASELINE. F2 = +1 → tips ↑."""
    _, tips_baseline, _ = apply_factor_model(_zero_z())
    assert math.isclose(tips_baseline, INITIAL_TIPS_BASELINE, abs_tol=1e-9)

    z = _zero_z()
    z["F2_inflation"] = 1.0
    _, tips_lifted, _ = apply_factor_model(z)
    assert tips_lifted > tips_baseline


# ---------------------------------------------------------------------------
# Per-contribution cap
# ---------------------------------------------------------------------------


def test_per_contribution_cap_applied():
    """F1 = +3 → kr_equity contribution clipped to +0.10, bond to -0.10."""
    z = _zero_z()
    z["F1_growth"] = 3.0
    _, _, contributions = apply_factor_model(z)
    # raw = 0.04 * 3 = 0.12 → cap = 0.10
    assert math.isclose(
        contributions["F1_growth"]["kr_equity"],
        PER_FACTOR_BUCKET_CONTRIB_CAP,
        abs_tol=1e-9,
    )
    # raw = -0.08 * 3 = -0.24 → cap = -0.10
    assert math.isclose(
        contributions["F1_growth"]["bond"],
        -PER_FACTOR_BUCKET_CONTRIB_CAP,
        abs_tol=1e-9,
    )


def test_per_contribution_cap_does_not_affect_small_signals():
    """F1 = +1 → kr_equity ≈ 0.04 (no cap), |contrib| < cap."""
    z = _zero_z()
    z["F1_growth"] = 1.0
    _, _, contributions = apply_factor_model(z)
    contrib = contributions["F1_growth"]["kr_equity"]
    assert abs(contrib) < PER_FACTOR_BUCKET_CONTRIB_CAP
    assert math.isclose(contrib, 0.04, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# apply_factor_model_with_safety — diagnostics
# ---------------------------------------------------------------------------


def test_apply_with_safety_diagnostics_returns_4_tuple():
    bucket, tips, contributions, diagnostics = apply_factor_model_with_safety(_zero_z())
    assert isinstance(bucket, dict)
    assert set(bucket.keys()) == set(BUCKETS)
    assert isinstance(tips, float)
    assert isinstance(contributions, dict)
    assert isinstance(diagnostics, dict)
    for key in (
        "pre_projection_risk_asset",
        "pre_projection_negatives",
        "pre_projection_sum",
        "mandate_violated_pre_projection",
        "extreme_factor_active",
        "projection_l2_distance",
        "projection_intervened",
    ):
        assert key in diagnostics, f"missing diagnostic key: {key}"


def test_safety_diagnostics_extreme_factor_flag():
    """F1 = +2.8 → extreme_factor_active = True."""
    z = _zero_z()
    z["F1_growth"] = 2.8
    _, _, _, diagnostics = apply_factor_model_with_safety(z)
    assert diagnostics["extreme_factor_active"] is True


def test_safety_diagnostics_mandate_violation_pre_projection():
    """Worst-case z 에서 mandate violation flag 가 작동 — 단, raw bucket 의 risk asset
    sum 이 > 0.70 인 경우. baseline = 0.47, 모든 factor 에서 risk asset 을 +방향으로
    밀어주면 0.70 초과 가능. 단순 sanity: flag 가 boolean 으로 존재.
    """
    # F1=+3, F4=+3, F7=-3 (vol regime negative → less defensive) etc 으로
    # risk asset 을 maximally push.
    z = _zero_z()
    z["F1_growth"] = +3.0
    z["F4_term_premium"] = +3.0
    z["F7_equity_vol_regime"] = -3.0
    z["F8_valuation"] = -3.0  # cheap → +equity
    _, _, _, diagnostics = apply_factor_model_with_safety(z)
    # mandate flag is boolean and equals (pre_risk > 0.70 + 1e-9)
    assert isinstance(diagnostics["mandate_violated_pre_projection"], bool)
    expected = diagnostics["pre_projection_risk_asset"] > 0.70 + 1e-9
    assert diagnostics["mandate_violated_pre_projection"] == expected


def test_safety_diagnostics_projection_distance():
    """projection_l2_distance >= 0 항상."""
    z = _zero_z()
    z["F1_growth"] = 2.0
    _, _, _, diagnostics = apply_factor_model_with_safety(z)
    assert diagnostics["projection_l2_distance"] >= 0.0


def test_safety_diagnostics_no_intervention_for_baseline():
    """All z = 0 → bucket = baseline (이미 mandate safe) → projection 작동 없음 (l2 ≈ 0)."""
    _, _, _, diagnostics = apply_factor_model_with_safety(_zero_z())
    assert diagnostics["projection_l2_distance"] < 1e-6
    assert diagnostics["projection_intervened"] is False
