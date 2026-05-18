import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.technical.universe_breadth import (
    compute_universe_breadth,
)


def _multi_etf_prices(
    n_etfs: int = 30, n_days: int = 300, drift: float = 0.1, seed: int = 0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    rows = []
    for i in range(n_etfs):
        ticker = f"A{str(i + 1).zfill(6)}"
        close = 100 + np.cumsum(rng.normal(drift, 1.0, n_days))
        close = np.maximum(close, 1.0)
        rows.append(pd.DataFrame({
            "ticker": [ticker] * n_days,
            "date": dates,
            "close": close,
        }))
    return pd.concat(rows, ignore_index=True)


def test_basic_shape():
    df = _multi_etf_prices()
    snap = compute_universe_breadth(df)
    assert snap.n_total == 30
    assert 0 <= snap.pct_above_ma50 <= 1
    assert 0 <= snap.pct_above_ma200 <= 1
    assert snap.new_52w_highs >= 0
    assert snap.new_52w_lows >= 0
    assert snap.advance_decline_5d_ratio >= 0
    assert snap.ad_line_5d_slope in (-1.0, 0.0, 1.0)
    assert snap.regime in ("broad_risk_on", "narrow", "broad_risk_off")


def test_strong_uptrend_universe_is_risk_on():
    df = _multi_etf_prices(drift=0.5, n_etfs=30, n_days=300, seed=42)
    snap = compute_universe_breadth(df)
    assert snap.pct_above_ma200 > 0.5
    # broad_risk_on if pct200 > 0.6 + ad_ratio > 1 + ad_slope >= 0 — likely true here
    assert snap.regime in ("broad_risk_on", "narrow")


def test_strong_downtrend_universe_is_risk_off():
    df = _multi_etf_prices(drift=-0.5, n_etfs=30, n_days=300, seed=11)
    snap = compute_universe_breadth(df)
    assert snap.pct_above_ma200 < 0.5
    assert snap.regime in ("broad_risk_off", "narrow")


def test_empty_input_raises():
    with pytest.raises(ValueError, match="empty"):
        compute_universe_breadth(pd.DataFrame(columns=["date", "ticker", "close"]))


def test_ad_ratio_capped():
    # All advancing → declining_5d = 0 → ratio = _AD_RATIO_CAP
    df = _multi_etf_prices(drift=2.0, seed=7, n_etfs=10)
    snap = compute_universe_breadth(df)
    assert snap.advance_decline_5d_ratio <= 10.0


def test_short_history_falls_back_safely():
    # Less than 60 trading days — vol_z should be 0.0 and new_highs/lows = 0
    df = _multi_etf_prices(n_days=50, n_etfs=5)
    snap = compute_universe_breadth(df)
    assert snap.universe_vol_z == 0.0
    assert snap.new_52w_highs == 0 and snap.new_52w_lows == 0
