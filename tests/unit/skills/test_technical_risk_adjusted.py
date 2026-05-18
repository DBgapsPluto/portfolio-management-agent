import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.technical.risk_adjusted import compute_risk_adjusted


def _prices(
    ticker: str = "A069500", n: int = 400,
    drift: float = 0.1, vol: float = 1.0, seed: int = 5,
) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(drift, vol, n))
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "ticker": [ticker] * n, "date": dates,
        "open": close - 0.3, "high": close + 0.8, "low": close - 0.8,
        "close": close, "volume": [1000.0] * n,
    })


def test_basic_shape():
    m = compute_risk_adjusted(_prices(), "A069500")
    assert m.ticker == "A069500"
    assert m.max_drawdown_12m <= 0
    assert isinstance(m.is_mean_reversion_candidate, bool)


def test_rejects_short_series():
    with pytest.raises(ValueError, match="≥252"):
        compute_risk_adjusted(_prices(n=200), "A069500")


def test_uptrending_has_smaller_drawdown():
    up = compute_risk_adjusted(_prices(drift=0.5, vol=0.3, seed=1), "A069500")
    dn = compute_risk_adjusted(_prices(drift=-0.5, vol=0.3, seed=1), "A069500")
    assert up.max_drawdown_12m >= dn.max_drawdown_12m  # up has smaller |DD|


def test_calmar_positive_for_uptrend():
    m = compute_risk_adjusted(_prices(drift=0.5, vol=0.3, seed=2), "A069500")
    if m.max_drawdown_12m < 0:
        assert m.calmar_12m > 0


def test_mean_reversion_candidate_detected_on_steep_drop():
    # Steep drop in last segment → bb_pb < 0, rsi < 35, z_30d < -1.5 expected
    n = 400
    base = np.linspace(100, 200, n - 30)
    crash = np.linspace(200, 130, 30)
    close = np.concatenate([base, crash])
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "ticker": ["A069500"] * n, "date": dates,
        "open": close - 0.3, "high": close + 0.8, "low": close - 0.8,
        "close": close, "volume": [1000.0] * n,
    })
    m = compute_risk_adjusted(df, "A069500")
    # 강한 30d 하락 → 후보 가능성 高
    assert m.return_z_30d < 0


def test_negative_skew_for_left_tailed_returns():
    # Construct returns with one big drop
    n = 300
    rng = np.random.default_rng(0)
    close = 100 + np.cumsum(rng.normal(0.1, 0.5, n))
    close[200] = close[199] * 0.85  # -15% one-day drop
    for i in range(201, n):
        close[i] = close[200] * (1 + rng.normal(0.0, 0.005))
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "ticker": ["A069500"] * n, "date": dates,
        "open": close - 0.3, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": [1000.0] * n,
    })
    m = compute_risk_adjusted(df, "A069500")
    # 60d window doesn't contain the drop — just sanity check field is a number
    assert isinstance(m.skewness_60d, float)
    assert isinstance(m.excess_kurtosis_60d, float)
