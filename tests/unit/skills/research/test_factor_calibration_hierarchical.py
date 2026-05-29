import numpy as np
import pytest
from tradingagents.skills.research.factor_calibration import HistoricalSample, HARD_ZERO_CELLS
from tradingagents.skills.research.factor_calibration_hierarchical import (
    hybrid_calibration_hierarchical, staggered_calibration,
)
from tradingagents.skills.research.factor_to_bucket import FACTORS, BUCKETS, INITIAL_BETA


def _synth_samples(n=60, seed=0, with_f11=True):
    rng = np.random.default_rng(seed)
    samples = []
    for i in range(n):
        fz = {f: float(rng.normal(0, 1)) for f in FACTORS}
        if not with_f11:
            fz["F11_earnings_revision"] = float("nan")
        # synthetic next returns loosely correlated with factor z
        br = {b: float(rng.normal(0.0, 0.05)) for b in BUCKETS}
        # date string: pre-2010 for first half, post for rest
        year = 2000 + i // 4
        samples.append(HistoricalSample(
            date=f"{year}-03-31", factor_z=fz, bucket_returns_next=br,
        ))
    return samples


def test_hierarchical_fit_clamps_hard_zeros():
    samples = _synth_samples(60, seed=1)
    beta, mu, sharpe = hybrid_calibration_hierarchical(samples, max_iter=30)
    # hard-zero cells must be exactly 0
    for k in HARD_ZERO_CELLS:
        assert beta[k] == 0.0, f"{k} not clamped to 0"
    # full 96-entry dict
    assert len(beta) == 96
    # mu has 60 entries (12 factor × 5 family)
    assert len(mu) == 60
    # all free beta within bounds
    for k, v in beta.items():
        assert -0.20 - 1e-6 <= v <= 0.20 + 1e-6


def test_hierarchical_fit_returns_finite_sharpe():
    samples = _synth_samples(60, seed=2)
    beta, mu, sharpe = hybrid_calibration_hierarchical(samples, max_iter=30)
    assert np.isfinite(sharpe)


def test_hierarchical_strong_shrinkage_stays_near_prior():
    """λ_global huge → β ≈ prior."""
    samples = _synth_samples(60, seed=3)
    beta, mu, _ = hybrid_calibration_hierarchical(
        samples, lambda_global=1e4, lambda_family=0.0, max_iter=50)
    max_dev = max(abs(beta[k] - INITIAL_BETA[k]) for k in beta if k not in HARD_ZERO_CELLS)
    assert max_dev < 0.05, f"strong shrinkage should keep β near prior, max_dev={max_dev}"


def test_staggered_calibration_runs():
    samples = _synth_samples(60, seed=4)
    pre = [s for s in samples if s.date < "2010-01-01"]
    post = [s for s in samples if s.date >= "2010-01-01"]
    beta, mu = staggered_calibration(pre, post)
    assert len(beta) == 96
    # F11 free cells bounded tighter (±0.10)
    f11_free = [k for k in beta if k[0] == "F11_earnings_revision" and k not in HARD_ZERO_CELLS]
    for k in f11_free:
        assert -0.10 - 1e-6 <= beta[k] <= 0.10 + 1e-6


def test_staggered_hard_zeros_still_zero():
    samples = _synth_samples(60, seed=5)
    pre = [s for s in samples if s.date < "2010-01-01"]
    post = [s for s in samples if s.date >= "2010-01-01"]
    beta, mu = staggered_calibration(pre, post)
    for k in HARD_ZERO_CELLS:
        assert beta[k] == 0.0
