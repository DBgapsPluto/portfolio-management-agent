"""factor_calibration unit tests (synthetic data)."""
from __future__ import annotations

import numpy as np

from tradingagents.skills.research.factor_calibration import (
    HistoricalSample,
    aggregate_median_beta,
    benchmark_60_40_returns,
    compute_sharpe,
    hybrid_calibration,
    simulate_portfolio_returns,
    walk_forward,
)
from tradingagents.skills.research.factor_to_bucket import FACTORS, INITIAL_BETA


def _synthetic_samples(n: int = 50, seed: int = 42) -> list[HistoricalSample]:
    np.random.seed(seed)
    samples = []
    for q in range(n):
        factor_z = {f: float(np.random.normal(0, 1)) for f in FACTORS}
        bucket_returns = {
            "kr_equity": 0.02 + 0.02 * factor_z["F1_growth"] + float(np.random.normal(0, 0.05)),
            "global_equity": 0.02 + 0.03 * factor_z["F1_growth"] + float(np.random.normal(0, 0.05)),
            "fx_commodity": 0.005 + float(np.random.normal(0, 0.04)),
            "bond": 0.01 - 0.01 * factor_z["F1_growth"] + float(np.random.normal(0, 0.02)),
            "cash_mmf": 0.005 + float(np.random.normal(0, 0.002)),
        }
        samples.append(
            HistoricalSample(
                date=f"2010-{(q % 12) + 1:02d}-01",
                factor_z=factor_z,
                bucket_returns_next=bucket_returns,
            )
        )
    return samples


def test_simulate_portfolio_returns_returns_array():
    samples = _synthetic_samples(10)
    rets = simulate_portfolio_returns(samples, INITIAL_BETA)
    assert isinstance(rets, np.ndarray)
    assert len(rets) == 10


def test_compute_sharpe_basic():
    rets = np.array([0.01, 0.02, -0.01, 0.015])
    sharpe = compute_sharpe(rets)
    assert isinstance(sharpe, float)
    assert sharpe != 0.0


def test_compute_sharpe_zero_std():
    rets = np.array([0.01, 0.01, 0.01])
    assert compute_sharpe(rets) == 0.0


def test_hybrid_calibration_returns_valid_beta():
    samples = _synthetic_samples(50)
    beta, sharpe = hybrid_calibration(samples, shrinkage=0.5)
    assert isinstance(beta, dict)
    assert len(beta) == len(INITIAL_BETA)
    # Each (factor, bucket) present
    for key in INITIAL_BETA:
        assert key in beta
    # Sharpe is finite
    assert np.isfinite(sharpe)


def test_walk_forward_produces_folds():
    samples = _synthetic_samples(100)
    folds = walk_forward(samples, initial_train_size=40, test_window=4)
    assert len(folds) > 0
    for f in folds:
        assert f.oos_sharpe is not None
        assert f.in_sample_sharpe is not None


def test_aggregate_median_beta():
    samples = _synthetic_samples(80)
    folds = walk_forward(samples, initial_train_size=40, test_window=4)
    median = aggregate_median_beta(folds)
    assert isinstance(median, dict)
    for key in INITIAL_BETA:
        assert key in median


def test_benchmark_60_40_returns():
    samples = _synthetic_samples(20)
    rets = benchmark_60_40_returns(samples)
    assert len(rets) == 20
