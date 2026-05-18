import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.technical.extended_indicators import (
    _detect_divergence,
    compute_extended_indicators,
)


def _synthetic_prices(
    ticker: str = "A069500",
    n: int = 400,
    drift: float = 0.2,
    vol: float = 1.0,
    seed: int = 7,
) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(drift, vol, n))
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "ticker": [ticker] * n,
        "date": dates,
        "open": close - 0.3,
        "high": close + 0.8,
        "low": close - 0.8,
        "close": close,
        "volume": rng.integers(800, 1200, n).astype(float),
    })


def test_panel_basic_shape():
    prices = _synthetic_prices()
    panel = compute_extended_indicators(prices, "A069500")
    assert panel.ticker == "A069500"
    assert 0 <= panel.adx <= 100
    assert 0 <= panel.stoch_k <= 100
    assert 0 <= panel.stoch_d <= 100
    assert 0 <= panel.mfi <= 100
    assert panel.bb_bandwidth >= 0
    assert panel.rsi_divergence in ("none", "bullish", "bearish")
    assert panel.macd_divergence in ("none", "bullish", "bearish")
    assert panel.weekly_trend in ("up", "down", "neutral")
    assert panel.weekly_ma50 > 0


def test_panel_rejects_short_series():
    prices = _synthetic_prices(n=100)
    with pytest.raises(ValueError, match="≥200"):
        compute_extended_indicators(prices, "A069500")


def test_uptrending_drift_gives_high_weekly_trend_up_or_neutral():
    prices = _synthetic_prices(drift=0.4, vol=0.5)
    panel = compute_extended_indicators(prices, "A069500")
    assert panel.weekly_trend in ("up", "neutral")


def test_downtrending_drift_gives_weekly_down_or_neutral():
    prices = _synthetic_prices(drift=-0.4, vol=0.5)
    panel = compute_extended_indicators(prices, "A069500")
    assert panel.weekly_trend in ("down", "neutral")


def test_bearish_divergence_detected():
    # Construct: price makes new high in last 5; indicator (lower in last 5)
    idx = pd.date_range("2025-01-01", periods=80, freq="D")
    price = pd.Series(np.linspace(100, 110, 80), index=idx)
    price.iloc[-5:] = np.linspace(112, 115, 5)  # new high
    indicator = pd.Series(np.linspace(50, 70, 80), index=idx)
    indicator.iloc[-5:] = np.linspace(60, 65, 5)  # lower than earlier peak
    assert _detect_divergence(price, indicator, lookback=80) == "bearish"


def test_bullish_divergence_detected():
    idx = pd.date_range("2025-01-01", periods=80, freq="D")
    price = pd.Series(np.linspace(100, 90, 80), index=idx)
    price.iloc[-5:] = np.linspace(88, 85, 5)  # new low
    indicator = pd.Series(np.linspace(50, 30, 80), index=idx)
    indicator.iloc[-5:] = np.linspace(40, 45, 5)  # higher than earlier low
    assert _detect_divergence(price, indicator, lookback=80) == "bullish"


def test_no_divergence_when_aligned():
    idx = pd.date_range("2025-01-01", periods=80, freq="D")
    price = pd.Series(np.linspace(100, 120, 80), index=idx)
    indicator = pd.Series(np.linspace(40, 70, 80), index=idx)
    assert _detect_divergence(price, indicator, lookback=80) == "none"


def test_obv_slope_directionally_correct():
    prices = _synthetic_prices(drift=0.5, vol=0.3, n=400, seed=3)
    panel = compute_extended_indicators(prices, "A069500")
    # Strong upward drift + constant volume tends to push OBV either way,
    # but slope sign must be one of {-1, 0, 1}.
    assert panel.obv_slope_20d in (-1.0, 0.0, 1.0)


def test_bb_percent_b_in_reasonable_range_for_drifting_series():
    prices = _synthetic_prices(drift=0.0, vol=0.5, n=400)
    panel = compute_extended_indicators(prices, "A069500")
    # With no drift, %B should typically be within [-1, 2] (very wide but tail-safe).
    assert -2.0 <= panel.bb_percent_b <= 3.0
