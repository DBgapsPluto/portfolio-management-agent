"""compute_realized_volatility tests (C6 — factor model F7 vol regime + F9 liquidity).

D7 pattern (신규 class indicator): full Snapshot return (analyst 가 RiskReport
의 Optional field 에 직접 채움; model_copy 아님).
D8 pattern: empty / short / exception → None (graceful skip, no default fill).
D9 pattern: no retry, no cache in skill — fresh compute each call.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.schemas.risk import RealVolSnapshot
from tradingagents.skills.risk.realized_volatility import compute_realized_volatility


def test_realized_vol_basic():
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0, 0.01, 100))
    result = compute_realized_volatility(returns, vix_level=20.0, as_of=date.today())

    assert isinstance(result, RealVolSnapshot)
    # annualized: 0.01 × sqrt(252) ≈ 0.158
    assert 0.10 < result.realized_vol_60d < 0.25


def test_realized_vol_vrp_positive_when_vix_above_realized():
    """VIX 20% (0.20) > realized 10% (0.10) → VRP positive."""
    # Daily returns 가 *very low std* → realized ≈ 0 → VRP ≈ VIX²
    np.random.seed(42)
    low_vol_returns = pd.Series(np.random.normal(0, 0.0001, 100))  # near-zero vol
    result = compute_realized_volatility(low_vol_returns, vix_level=20.0, as_of=date.today())
    # VIX² = 400/10000 = 0.04 → scaled × 10000 = 400 bps²
    assert result.vrp_60d > 300  # high VRP


def test_realized_vol_vix_none_zero_vrp():
    """VIX None → vrp = 0."""
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0, 0.01, 60))
    result = compute_realized_volatility(returns, vix_level=None, as_of=date.today())
    assert result.vrp_60d == 0.0


def test_realized_vol_empty_returns_none():
    """Empty series → None (skill graceful)."""
    empty = pd.Series([], dtype=float)
    result = compute_realized_volatility(empty, vix_level=20.0, as_of=date.today())
    assert result is None


def test_realized_vol_short_returns_partial():
    """< 5 obs → None."""
    short = pd.Series([0.01, 0.02])
    result = compute_realized_volatility(short, vix_level=20.0, as_of=date.today())
    assert result is None
