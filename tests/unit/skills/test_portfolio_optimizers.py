import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.portfolio.optimizers import (
    optimize_hrp, optimize_risk_parity, optimize_min_variance,
    optimize_black_litterman,
)


@pytest.fixture
def returns_5_assets():
    """Generate 252 days of returns for 5 assets."""
    rng = np.random.default_rng(42)
    n = 252
    return pd.DataFrame({
        f"A0000{i:02d}": rng.normal(0.001, 0.015, n)
        for i in range(1, 6)
    })


class TestHRP:
    def test_hrp_weights_sum_to_one(self, returns_5_assets):
        wv = optimize_hrp(returns_5_assets)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
        assert all(0 <= w <= 1 for w in wv.weights.values())

    def test_hrp_returns_all_assets(self, returns_5_assets):
        wv = optimize_hrp(returns_5_assets)
        assert len(wv.weights) == 5


class TestRiskParity:
    def test_risk_parity_weights_sum_to_one(self, returns_5_assets):
        wv = optimize_risk_parity(returns_5_assets)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-3
        assert all(0 <= w <= 1 for w in wv.weights.values())

    def test_risk_parity_respects_cap(self, returns_5_assets):
        wv = optimize_risk_parity(returns_5_assets)
        assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())


class TestMinVariance:
    def test_min_variance_weights_sum_to_one(self, returns_5_assets):
        wv = optimize_min_variance(returns_5_assets)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
        assert all(0 <= w <= 1 for w in wv.weights.values())

    def test_min_variance_respects_cap(self, returns_5_assets):
        wv = optimize_min_variance(returns_5_assets)
        assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())

    def test_min_variance_returns_metrics(self, returns_5_assets):
        wv = optimize_min_variance(returns_5_assets)
        assert wv.expected_volatility is not None
        assert wv.expected_sharpe is not None


class TestBlackLitterman:
    def test_black_litterman_weights_sum_to_one(self, returns_5_assets):
        views = {"A000001": 0.02, "A000002": 0.015}
        view_confidences = [0.8, 0.6]
        wv = optimize_black_litterman(returns_5_assets, views, view_confidences)
        assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
        assert all(0 <= w <= 1 for w in wv.weights.values())

    def test_black_litterman_respects_cap(self, returns_5_assets):
        views = {"A000001": 0.02, "A000002": 0.015}
        view_confidences = [0.8, 0.6]
        wv = optimize_black_litterman(returns_5_assets, views, view_confidences)
        assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
