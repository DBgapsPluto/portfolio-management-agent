"""Phase 4a Ledoit-Wolf shrinkage unit tests."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov


def _make_returns(n_obs=252, n_assets=5, seed=42):
    rng = np.random.default_rng(seed)
    data = rng.normal(0.0005, 0.012, size=(n_obs, n_assets))
    columns = [f"A{i:03d}" for i in range(n_assets)]
    return pd.DataFrame(data, columns=columns)


def test_compute_robust_cov_basic_returns_dataframe():
    returns = _make_returns()
    cov = compute_robust_cov(returns)
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (5, 5)
    assert list(cov.index) == list(returns.columns)
    assert list(cov.columns) == list(returns.columns)


def test_compute_robust_cov_records_breakdown():
    returns = _make_returns()
    breakdown: dict = {}
    cov = compute_robust_cov(returns, breakdown_out=breakdown)
    assert breakdown["estimator"] == "ledoit_wolf"
    assert "shrinkage_intensity" in breakdown
    assert breakdown["n_obs"] == 252
    assert breakdown["n_assets"] == 5


def test_compute_robust_cov_shrinkage_intensity_in_unit_interval():
    returns = _make_returns()
    breakdown: dict = {}
    compute_robust_cov(returns, breakdown_out=breakdown)
    delta = breakdown["shrinkage_intensity"]
    assert 0.0 <= delta <= 1.0


def test_compute_robust_cov_is_psd():
    returns = _make_returns()
    cov = compute_robust_cov(returns)
    eigenvalues = np.linalg.eigvalsh(cov.values)
    assert (eigenvalues >= -1e-10).all()


def test_compute_robust_cov_differs_from_sample_cov():
    from pypfopt import risk_models
    returns = _make_returns()
    cov_shrunk = compute_robust_cov(returns)
    cov_sample = risk_models.sample_cov(returns, returns_data=True)
    assert not np.allclose(cov_shrunk.values, cov_sample.values, atol=1e-12)


def test_compute_robust_cov_fallback_on_failure():
    constant = pd.DataFrame(np.zeros((252, 3)), columns=["A", "B", "C"])
    breakdown: dict = {}
    cov = compute_robust_cov(constant, breakdown_out=breakdown)
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (3, 3)
    assert "estimator" in breakdown or "fallback_reason" in breakdown
