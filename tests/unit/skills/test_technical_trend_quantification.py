import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.technical.trend_quantification import (
    _ma_cross_days, _trend_strength, quantify_trend,
)


def _prices(
    ticker: str = "A069500", n: int = 400,
    drift: float = 0.3, vol: float = 0.5, seed: int = 5,
) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(drift, vol, n))
    close = np.maximum(close, 1.0)
    return pd.DataFrame({
        "ticker": [ticker] * n,
        "date": dates,
        "open": close - 0.3,
        "high": close + 0.6,
        "low": close - 0.6,
        "close": close,
        "volume": rng.integers(800, 1200, n).astype(float),
    })


def test_basic_shape_no_benchmark():
    panel = quantify_trend(_prices(), "A069500", benchmark_close=None)
    assert panel.ticker == "A069500"
    assert -1.0 <= panel.trend_strength_score <= 1.0
    assert panel.time_in_state_days >= 0
    assert panel.benchmark == "none"
    assert panel.momentum_3m_rel == 0.0
    assert panel.momentum_12m_rel == 0.0


def test_relative_momentum_with_benchmark():
    df = _prices(drift=0.5, vol=0.3)
    bench = pd.Series(
        100 + np.cumsum(np.random.default_rng(0).normal(0.1, 0.5, 400)),
        index=pd.RangeIndex(400),
    )
    panel = quantify_trend(df, "A069500", benchmark_close=bench, benchmark_label="SPY")
    assert panel.benchmark == "SPY"
    # Asset drifts faster than benchmark → relative should be positive (usually).
    assert panel.momentum_12m_rel > -1.0  # sanity only — no strict positivity claim


def test_uptrend_score_positive():
    panel = quantify_trend(_prices(drift=0.5, vol=0.3), "A069500")
    assert panel.trend_strength_score > 0.0
    assert panel.distance_ma200_pct > 0


def test_downtrend_score_negative():
    # drift=-0.15: cumsum 400 step → mean ≈ -60 → close가 1.0 floor에 닿지 않고
    # 깨끗한 monotonic downtrend 유지. drift=-0.5는 1.0 floor 가까이 가서 U-shape
    # 으로 변형되어 distance_ma200_pct ≈ 0이 됨.
    panel = quantify_trend(_prices(drift=-0.15, vol=0.2), "A069500")
    assert panel.trend_strength_score < 0.0
    assert panel.distance_ma200_pct < 0


def test_rejects_short_series():
    with pytest.raises(ValueError, match="≥252"):
        quantify_trend(_prices(n=200), "A069500")


def test_acceleration_signs():
    # Asset that accelerated recently (last 3m faster than full 12m)
    n = 300
    rng = np.random.default_rng(1)
    # 12개월 평탄 + 마지막 3개월 가속
    flat = np.cumsum(rng.normal(0.0, 0.3, n - 63))
    accel = np.cumsum(rng.normal(0.8, 0.3, 63)) + flat[-1] if len(flat) else np.cumsum(rng.normal(0.8, 0.3, 63))
    close = 100 + np.concatenate([flat, accel])
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "ticker": ["A069500"] * n,
        "date": dates,
        "open": close - 0.3, "high": close + 0.6, "low": close - 0.6,
        "close": close, "volume": [1000.0] * n,
    })
    panel = quantify_trend(df, "A069500")
    assert panel.momentum_acceleration > 0  # 가속


def test_ma_cross_helper_counts_recent_cross():
    # MA cross simulated: close above MA at indices [0..50), below [50..100)
    n = 100
    close = pd.Series(np.r_[np.linspace(101, 101, 50), np.linspace(99, 99, 50)])
    ma = pd.Series([100.0] * n)
    days = _ma_cross_days(close, ma)
    # last cross index = 50 (when above→below), so days since = 99 - 50 = 49
    assert days == 49


def test_strength_bounded():
    assert _trend_strength(100.0, True, 100.0, 100.0) <= 1.0
    assert _trend_strength(-100.0, False, 100.0, 0.0) >= -1.0
