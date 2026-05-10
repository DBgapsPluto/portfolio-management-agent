import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.technical.ta_indicators import compute_ta_indicators


def _synthetic_prices(ticker: str, n: int = 250) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0.5, 1.0, n))
    return pd.DataFrame({
        "ticker": [ticker] * n,
        "date": dates,
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": [1000] * n,
    })


def test_compute_indicators_returns_panel():
    prices = _synthetic_prices("A069500")
    panel = compute_ta_indicators(prices, "A069500")
    assert panel.ticker == "A069500"
    assert panel.ma200 > 0
    assert 0 <= panel.rsi <= 100
    assert panel.atr >= 0


def test_compute_indicators_rejects_short_series():
    prices = _synthetic_prices("A069500", n=100)  # < 200
    with pytest.raises(ValueError, match="≥200 data points"):
        compute_ta_indicators(prices, "A069500")
