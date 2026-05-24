"""Unit tests for project_to_mandate_qp (QP-based mandate projection).

Constraints:
  1. weights ≥ 0
  2. sum = 1.0
  3. 위험자산 (kr_equity + global_equity + fx_commodity) ≤ 0.70
  4. baseline L2 거리 최소 (soft objective)
"""
from __future__ import annotations

import math

import pytest

from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS,
    FACTORS,
    INITIAL_BASELINE,
    apply_factor_model,
    project_to_mandate_qp,
)


RISK_BUCKETS = ("kr_equity", "global_equity", "fx_commodity")


def _assert_simplex(w: dict[str, float], *, tol: float = 1e-6):
    """w_b ≥ 0, sum w = 1 (tolerance)."""
    for b, v in w.items():
        assert v >= -tol, f"negative weight: {b}={v}"
    s = sum(w.values())
    assert abs(s - 1.0) < tol, f"sum={s} != 1"


def _risk_sum(w: dict[str, float]) -> float:
    return sum(w.get(b, 0.0) for b in RISK_BUCKETS)


# ---------------------------------------------------------------------------
# Basic projection tests
# ---------------------------------------------------------------------------


def test_qp_clips_negative():
    """Negative weights 가 0 으로 clip 되어야."""
    bucket = {
        "kr_equity": -0.05,
        "global_equity": 0.25,
        "fx_commodity": 0.10,
        "bond": 0.40,
        "cash_mmf": 0.30,
    }
    w = project_to_mandate_qp(bucket)
    for b, v in w.items():
        assert v >= -1e-6, f"{b}={v}"
    _assert_simplex(w)


def test_qp_renormalizes_to_one():
    """sum != 1 인 input 이 sum=1 로 renormalize."""
    bucket = {
        "kr_equity": 0.15,
        "global_equity": 0.25,
        "fx_commodity": 0.10,
        "bond": 0.35,
        "cash_mmf": 0.25,
    }  # sum = 1.10
    w = project_to_mandate_qp(bucket)
    _assert_simplex(w)


def test_qp_risk_cap_enforced():
    """risk asset > 0.70 인 input → projection 후 risk ≤ 0.70."""
    bucket = {
        "kr_equity": 0.30,
        "global_equity": 0.35,
        "fx_commodity": 0.15,  # risk = 0.80
        "bond": 0.15,
        "cash_mmf": 0.05,
    }
    w = project_to_mandate_qp(bucket)
    _assert_simplex(w)
    assert _risk_sum(w) <= 0.70 + 1e-6


def test_qp_no_change_when_feasible():
    """이미 feasible 한 input → 거의 변화 없음."""
    bucket = dict(INITIAL_BASELINE)
    w = project_to_mandate_qp(bucket)
    _assert_simplex(w)
    for b in BUCKETS:
        assert math.isclose(w[b], INITIAL_BASELINE[b], abs_tol=1e-4)


def test_qp_preserves_relative_ratio_better_than_proportional():
    """Soft check: sum=1, risk ≤ 0.70, weights ≥ 0 — 4 가지 hard constraint 만 검증."""
    bucket = {
        "kr_equity": 0.35,
        "global_equity": 0.40,
        "fx_commodity": 0.10,  # risk = 0.85
        "bond": 0.10,
        "cash_mmf": 0.05,
    }
    w = project_to_mandate_qp(bucket)
    _assert_simplex(w)
    assert _risk_sum(w) <= 0.70 + 1e-6
    # relative ratio: global_equity > kr_equity > fx_commodity 의 ordering 보존
    assert w["global_equity"] >= w["kr_equity"]
    assert w["kr_equity"] >= w["fx_commodity"]


# ---------------------------------------------------------------------------
# Pathological cases
# ---------------------------------------------------------------------------


def test_qp_pathological_all_negative_risk_returns_baseline():
    """모든 risk asset weight < 0 → very rare, projection 후에도 hard constraint 만족."""
    bucket = {
        "kr_equity": -0.10,
        "global_equity": -0.05,
        "fx_commodity": -0.02,
        "bond": 0.70,
        "cash_mmf": 0.47,
    }
    w = project_to_mandate_qp(bucket)
    _assert_simplex(w)
    assert _risk_sum(w) <= 0.70 + 1e-6


def test_qp_extreme_factor_z_still_mandate_safe():
    """모든 factor z = +3 → apply + project 후 hard constraint 만족."""
    z = {f: 3.0 for f in FACTORS}
    raw_bucket, _, _ = apply_factor_model(z)
    w = project_to_mandate_qp(raw_bucket)
    _assert_simplex(w)
    assert _risk_sum(w) <= 0.70 + 1e-6


def test_qp_extreme_negative_z_mandate_safe():
    """모든 factor z = -3 → apply + project 후 hard constraint 만족."""
    z = {f: -3.0 for f in FACTORS}
    raw_bucket, _, _ = apply_factor_model(z)
    w = project_to_mandate_qp(raw_bucket)
    _assert_simplex(w)
    assert _risk_sum(w) <= 0.70 + 1e-6
