"""Fake PyPortfolioOpt deterministic optimizer for tests."""
from __future__ import annotations


def fake_optimize_hrp(returns):
    """Returns equal-weighted across input tickers."""
    n = returns.shape[1]
    return {col: 1.0 / n for col in returns.columns}


def fake_optimize_min_variance(returns):
    """Equal-weighted as a deterministic stand-in."""
    n = returns.shape[1]
    return {col: 1.0 / n for col in returns.columns}
