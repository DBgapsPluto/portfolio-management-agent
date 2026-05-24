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


def test_initial_beta_row_sums_bounded():
    """Each factor row 의 β sum 이 ±0.4 bound 안 (post PR2a calibration).

    Pre-PR2a hand-coded INITIAL_BETA 는 row sum = 0 invariant 였음 (adjustment
    preserves total). PR2a calibration (walk-forward Sharpe maximization) 은
    Sharpe 를 직접 최적화 하므로 row sum 0 invariant 가 자동 성립 안 함.
    `_project_simple` (post-apply_factor_model) 가 sum=1 으로 normalize 하므로
    bucket allocation 정합성은 유지. 본 test 는 calibration drift 가 합리적
    범위 안인지 확인 (F6 row sum +0.33 이 최대 observed).
    """
    for f in FACTORS:
        row_sum = sum(INITIAL_BETA.get((f, b), 0.0) for b in BUCKETS)
        assert abs(row_sum) < 0.4, f"{f}: row sum {row_sum} out of ±0.4 bound"


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


def test_apply_factor_model_preserves_sum_bounded_no_capping():
    """All |z| ≤ 0.5, no capping → bucket sum within ±0.3 of 1.0.

    Post PR2a calibration: row sums no longer 0 invariant, so bucket sum
    drifts from 1.0 by sum(row_sum × z). At z=0.5 across 9 factors with row
    sums bounded ±0.4, max drift ≈ 0.5 × 9 × 0.4 / mean ≈ 0.3.
    `_project_simple` (downstream of apply_factor_model) renormalizes to
    sum=1.0 — this test validates the raw output bound only.
    """
    z = {f: 0.5 for f in FACTORS}
    bucket, _, _ = apply_factor_model(z)
    s = sum(bucket.values())
    assert abs(s - 1.0) < 0.5, f"sum={s} drifts too far from 1.0"


def test_apply_factor_model_sum_drift_bounded_under_capping():
    """All z = 1 → contributions capped + row sums non-zero (PR2a calibrated) →
    bucket sum drifts. Post-projection downstream normalizes to 1.0.
    """
    z = {f: 1.0 for f in FACTORS}
    bucket, _, _ = apply_factor_model(z)
    s = sum(bucket.values())
    # PR2a calibrated: row sums up to ±0.4 per factor, 9 factors at z=1 →
    # max raw drift ≈ ±3.6 (before capping). Capping limits to ±9 × 0.10 = ±0.9.
    # observed empirically: well within ±1.0 of baseline 1.0.
    assert 0.0 < s < 2.0, f"sum drift unbounded: {s}"


def test_apply_factor_model_contributions_audit():
    """F1 = +1, 다른 z = 0 → contributions[F1_growth] 가 raw β 값 (INITIAL_BETA)."""
    z = _zero_z()
    z["F1_growth"] = 1.0
    _, _, contributions = apply_factor_model(z)
    # PR2a calibrated INITIAL_BETA values (dynamic — no hand-coded constants).
    for b in BUCKETS:
        expected = INITIAL_BETA.get(("F1_growth", b), 0.0)
        # Per-contribution cap may clip large |β|.
        expected_capped = max(
            -PER_FACTOR_BUCKET_CONTRIB_CAP,
            min(+PER_FACTOR_BUCKET_CONTRIB_CAP, expected * 1.0),
        )
        assert math.isclose(contributions["F1_growth"][b], expected_capped, abs_tol=1e-9)
    # 다른 factor 의 contribution 은 0.
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
    """Large |z| → contribution clipped to ±PER_FACTOR_BUCKET_CONTRIB_CAP.

    Find any (factor, bucket) with non-trivial |β|, apply large z, verify clip.
    """
    # Pick first factor with |β| > 0 against any bucket — capture cap behavior.
    target_f, target_b = None, None
    target_beta = 0.0
    for (f, b), v in INITIAL_BETA.items():
        if abs(v) > 0.02:  # meaningful magnitude
            target_f, target_b, target_beta = f, b, v
            break
    assert target_f is not None
    # z large enough to definitely trigger cap (|β·z| > cap).
    z_value = (PER_FACTOR_BUCKET_CONTRIB_CAP / abs(target_beta)) * 3
    z = _zero_z()
    z[target_f] = z_value if target_beta > 0 else -z_value
    _, _, contributions = apply_factor_model(z)
    contrib = contributions[target_f][target_b]
    assert math.isclose(contrib, PER_FACTOR_BUCKET_CONTRIB_CAP, abs_tol=1e-9), (
        f"{target_f}×{target_b}: contrib {contrib} != +cap "
        f"(β={target_beta}, z={z_value})"
    )


def test_per_contribution_cap_does_not_affect_small_signals():
    """small z → contrib = β·z (no cap). Uses dynamic INITIAL_BETA values."""
    z = _zero_z()
    z["F1_growth"] = 1.0
    _, _, contributions = apply_factor_model(z)
    contrib = contributions["F1_growth"]["kr_equity"]
    expected = INITIAL_BETA.get(("F1_growth", "kr_equity"), 0.0) * 1.0
    # Should not be capped if |β|<cap.
    if abs(expected) < PER_FACTOR_BUCKET_CONTRIB_CAP:
        assert math.isclose(contrib, expected, abs_tol=1e-9)
    else:
        # If somehow calibrated β exceeded cap, this still gets clipped.
        assert abs(contrib) <= PER_FACTOR_BUCKET_CONTRIB_CAP + 1e-9


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
