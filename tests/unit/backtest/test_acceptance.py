"""Unit tests for acceptance.py — strict default 5-condition gate (Critical 3)."""
from dataclasses import dataclass

import pytest

from tradingagents.backtest.acceptance import evaluate_acceptance
from tradingagents.skills.research.factor_to_bucket import (
    INITIAL_BETA, SIGN_RESTRICTION,
)


@dataclass
class FakeFold:
    fold_idx: int
    in_sample_sharpe: float
    oos_sharpe: float
    beta: dict
    train_end_idx: int = 0
    test_start_idx: int = 0
    test_end_idx: int = 0


def _good_calibrated_beta():
    """Calibrated β = INITIAL_BETA × 1.1 — sign respect 유지."""
    return {k: v * 1.1 for k, v in INITIAL_BETA.items()}


def _good_folds():
    return [FakeFold(i, 0.6, 0.5 + 0.01 * i, _good_calibrated_beta())
            for i in range(7)]


def test_acceptance_pass_default_strict() -> None:
    """default strict — all conditions pass."""
    folds = _good_folds()
    verdict = evaluate_acceptance(
        calibrated_beta=_good_calibrated_beta(),
        calibrated_folds=folds,
        prior_oos_per_fold=[0.3 + 0.005 * i for i in range(7)],
        prior_oos_mean=0.32,
        equi_oos_mean=0.1,
        vintage_sanity={"pass": True, "skipped": False, "avg_abs_diff": 0.02},
        learning_sensitivity=0.05,
    )
    assert verdict["pass"]
    assert verdict["conditions"]["improvement"]
    assert verdict["conditions"]["overfit_guard"]
    assert verdict["conditions"]["sign_respect"]
    assert verdict["conditions"]["saturation"]
    assert verdict["conditions"]["fold_positive"]


def test_acceptance_fail_overfit() -> None:
    """IS Sharpe 1.5, OOS 0.5 → overfit guard FAIL (Δ=1.0 > 0.30)."""
    folds = [FakeFold(i, 1.5, 0.5, _good_calibrated_beta()) for i in range(7)]
    verdict = evaluate_acceptance(
        calibrated_beta=_good_calibrated_beta(),
        calibrated_folds=folds,
        prior_oos_per_fold=[0.3] * 7,
        prior_oos_mean=0.3,
        equi_oos_mean=0.1,
        vintage_sanity={"pass": True, "skipped": True, "avg_abs_diff": 0.0},
        learning_sensitivity=0.05,
    )
    assert not verdict["pass"]
    assert not verdict["conditions"]["overfit_guard"]


def test_acceptance_fail_sign_violation() -> None:
    """β 의 sign 이 SIGN_RESTRICTION 위반."""
    bad_beta = dict(INITIAL_BETA)
    # Flip an arbitrary sign-restricted key to the wrong sign.
    sign_restricted = [(k, expected) for k, expected in SIGN_RESTRICTION.items()
                        if expected in ("positive", "negative") and k in bad_beta]
    if not sign_restricted:
        pytest.skip("no sign-restricted keys to flip")
    k, expected = sign_restricted[0]
    if expected == "negative":
        bad_beta[k] = abs(bad_beta[k]) + 0.05  # force positive
    else:
        bad_beta[k] = -abs(bad_beta[k]) - 0.05  # force negative
    folds = [FakeFold(i, 0.6, 0.5, bad_beta) for i in range(7)]
    verdict = evaluate_acceptance(
        calibrated_beta=bad_beta,
        calibrated_folds=folds,
        prior_oos_per_fold=[0.3] * 7,
        prior_oos_mean=0.3,
        equi_oos_mean=0.1,
        vintage_sanity={"pass": True, "skipped": True, "avg_abs_diff": 0.0},
        learning_sensitivity=0.05,
    )
    assert not verdict["conditions"]["sign_respect"]


def test_acceptance_fail_fold_positive() -> None:
    """fold positive 5/7 (lenient 였던 것) — strict 에선 ≥6/7 — FAIL."""
    folds = [FakeFold(i, 0.4, (0.1 if i < 5 else -0.1), _good_calibrated_beta())
             for i in range(7)]
    verdict = evaluate_acceptance(
        calibrated_beta=_good_calibrated_beta(),
        calibrated_folds=folds,
        prior_oos_per_fold=[0.05] * 7,
        prior_oos_mean=0.05,
        equi_oos_mean=0.0,
        vintage_sanity={"pass": True, "skipped": True, "avg_abs_diff": 0.0},
        learning_sensitivity=0.05,
    )
    assert not verdict["conditions"]["fold_positive"]


def test_acceptance_paired_t_p_in_verdict() -> None:
    """paired_t_p field 가 verdict 에 포함."""
    folds = _good_folds()
    verdict = evaluate_acceptance(
        calibrated_beta=_good_calibrated_beta(),
        calibrated_folds=folds,
        prior_oos_per_fold=[0.25] * 7,
        prior_oos_mean=0.25,
        equi_oos_mean=0.1,
        vintage_sanity={"pass": True, "skipped": True, "avg_abs_diff": 0.0},
        learning_sensitivity=0.05,
    )
    assert "paired_t_p" in verdict
    assert 0.0 <= verdict["paired_t_p"] <= 1.0
