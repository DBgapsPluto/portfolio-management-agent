import numpy as np
from tradingagents.skills.research.factor_calibration import HistoricalSample
from tradingagents.skills.research.factor_calibration_tips import (
    hybrid_calibration_tips, HARD_ZERO_TIPS,
)
from tradingagents.skills.research.factor_to_bucket import FACTORS, INITIAL_TIPS_BETA


def _synth(n=80, seed=0):
    rng = np.random.default_rng(seed)
    samples = []
    for i in range(n):
        fz = {f: float(rng.normal(0, 1)) for f in FACTORS}
        # realized tips share loosely driven by F2_inflation (real link)
        share = 0.30 + 0.20 * fz["F2_inflation"] + rng.normal(0, 0.02)
        share = max(0.0, min(1.0, share))
        samples.append(HistoricalSample(
            date=f"{2000+i//4}-03-31", factor_z=fz,
            bucket_returns_next={}, tips_share_realized=share,
        ))
    return samples


def test_tips_calibration_clamps_hard_zeros():
    samples = _synth(80, seed=1)
    beta, mse = hybrid_calibration_tips(samples, max_iter=50)
    assert beta["F11_earnings_revision"] == 0.0
    assert beta["F12_china_credit_impulse"] == 0.0
    # 12 entries total
    assert len(beta) == 12
    for f in FACTORS:
        assert f in beta


def test_tips_calibration_recovers_inflation_link():
    """Synthetic data has tips ∝ +0.20·F2_inflation → calibrated β_F2 should be positive."""
    samples = _synth(120, seed=2)
    beta, mse = hybrid_calibration_tips(samples, lambda_global=0.1, max_iter=80)
    assert beta["F2_inflation"] > 0.05, f"F2 inflation link not recovered: {beta['F2_inflation']}"
    assert np.isfinite(mse)


def test_tips_calibration_no_realized_returns_high_mse():
    """Samples lacking tips_share_realized → objective returns sentinel (no fit)."""
    samples = [
        HistoricalSample(date="2020-03-31", factor_z={f: 0.0 for f in FACTORS},
                         bucket_returns_next={}, tips_share_realized=None)
    ]
    beta, mse = hybrid_calibration_tips(samples, max_iter=10)
    # No valid samples → mse sentinel large (1e6) + prior penalty 0 at x0=prior
    assert mse >= 1e6 - 1


def test_tips_strong_shrinkage_near_prior():
    samples = _synth(80, seed=3)
    beta, _ = hybrid_calibration_tips(samples, lambda_global=1e4, max_iter=50)
    free = [f for f in INITIAL_TIPS_BETA if f not in HARD_ZERO_TIPS]
    max_dev = max(abs(beta[f] - INITIAL_TIPS_BETA[f]) for f in free)
    assert max_dev < 0.05
