"""Tier 2 integration: synthetic samples → hierarchical fit → validate.

No external data — synthetic samples with a planted factor→return signal,
verifying the calibration framework composes end-to-end.
"""
import numpy as np
import pytest

from tradingagents.skills.research.factor_calibration import (
    HistoricalSample, HARD_ZERO_CELLS, compute_vif_matrix, compute_effective_df,
)
from tradingagents.skills.research.factor_calibration_hierarchical import (
    hybrid_calibration_hierarchical, staggered_calibration,
)
from tradingagents.skills.research.factor_calibration_tips import (
    hybrid_calibration_tips,
)
from tradingagents.skills.research.factor_to_bucket import FACTORS, BUCKETS, INITIAL_BETA


def _synth(n=100, seed=0):
    rng = np.random.default_rng(seed)
    samples = []
    for i in range(n):
        fz = {f: float(rng.normal(0, 1)) for f in FACTORS}
        # planted signal: kr_equity next return ∝ +0.02·F1_growth
        br = {b: float(rng.normal(0, 0.04)) for b in BUCKETS}
        br["kr_equity"] += 0.02 * fz["F1_growth"]
        tips = max(0.0, min(1.0, 0.30 + 0.15 * fz["F2_inflation"] + rng.normal(0, 0.02)))
        samples.append(HistoricalSample(
            date=f"{2000 + i // 4}-03-31", factor_z=fz,
            bucket_returns_next=br, tips_share_realized=tips,
        ))
    return samples


def test_full_pipeline_hierarchical_then_validate():
    samples = _synth(100, seed=1)
    beta, mu, sharpe = hybrid_calibration_hierarchical(samples, max_iter=40)
    # structural invariants
    assert len(beta) == 96
    assert len(mu) == 60
    for k in HARD_ZERO_CELLS:
        assert beta[k] == 0.0
    assert np.isfinite(sharpe)
    # VIF on independent synthetic factors → all low
    vif = compute_vif_matrix(samples, list(FACTORS))
    assert float(np.nanmax(vif.values)) < 5.0
    # effective df finite + positive
    X = np.array([[s.factor_z[f] for f in FACTORS] for s in samples])
    df = compute_effective_df(X, 2.0)
    assert 0 < df <= len(FACTORS)


def test_full_pipeline_staggered_and_tips():
    samples = _synth(100, seed=2)
    pre = [s for s in samples if s.date < "2010-01-01"]
    post = [s for s in samples if s.date >= "2010-01-01"]
    beta, mu = staggered_calibration(pre, post)
    assert len(beta) == 96
    for k in HARD_ZERO_CELLS:
        assert beta[k] == 0.0
    tips_beta, mse = hybrid_calibration_tips(samples, lambda_global=0.1, max_iter=60)
    assert tips_beta["F11_earnings_revision"] == 0.0
    assert tips_beta["F12_china_credit_impulse"] == 0.0
    # planted +0.15·F2_inflation tips signal recovered (positive)
    assert tips_beta["F2_inflation"] > 0.03
    assert np.isfinite(mse)
