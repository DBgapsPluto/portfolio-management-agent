"""Tier-1 extended indicators — Bollinger / ADX / Stochastic / Volume / Divergence / Weekly."""
from typing import Literal

import numpy as np
import pandas as pd
import pandas_ta as ta

from tradingagents.schemas.technical import ExtendedIndicatorPanel
from tradingagents.skills.registry import register_skill


def _detect_divergence(
    price: pd.Series, indicator: pd.Series, lookback: int = 60, recent_window: int = 5,
) -> Literal["none", "bullish", "bearish"]:
    """Peak/trough divergence between price and indicator over the lookback window.

    bearish: price made a new high in the recent window vs prior period,
             but indicator failed to make a new high. (uptrend losing strength)
    bullish: price made a new low in the recent window vs prior period,
             but indicator failed to make a new low. (downtrend losing strength)
    """
    df = pd.concat([price.rename("p"), indicator.rename("i")], axis=1).dropna().tail(lookback)
    if len(df) < 20:
        return "none"
    recent = df.iloc[-recent_window:]
    earlier = df.iloc[:-recent_window]
    if recent.empty or earlier.empty:
        return "none"

    if recent["p"].max() > earlier["p"].max() and recent["i"].max() < earlier["i"].max():
        return "bearish"
    if recent["p"].min() < earlier["p"].min() and recent["i"].min() > earlier["i"].min():
        return "bullish"
    return "none"


def _obv_slope(obv: pd.Series, window: int = 20) -> float:
    """Slope sign as +1/0/-1 from a linear fit over the last `window` values."""
    last = obv.dropna().tail(window)
    if len(last) < 5:
        return 0.0
    x = np.arange(len(last), dtype=float)
    y = last.values.astype(float)
    slope = float(np.polyfit(x, y, 1)[0])
    if slope > 0:
        return 1.0
    if slope < 0:
        return -1.0
    return 0.0


@register_skill(name="compute_extended_indicators", category="technical")
def compute_extended_indicators(
    prices: pd.DataFrame, ticker: str,
) -> ExtendedIndicatorPanel:
    """Compute Tier-1 extended indicator panel for one ticker.

    Args:
        prices: DataFrame with columns [date, open, high, low, close, volume, ticker].
        ticker: Single ticker filter.
    """
    sub = prices[prices["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    if len(sub) < 200:
        raise ValueError(f"Need ≥200 data points for {ticker}, got {len(sub)}")

    close = sub["close"].astype(float)
    high = sub["high"].astype(float)
    low = sub["low"].astype(float)
    volume = sub["volume"].astype(float)

    bb = ta.bbands(close, length=20, std=2.0)
    bb_lower = float(bb.iloc[-1, 0])
    bb_mid = float(bb.iloc[-1, 1])
    bb_upper = float(bb.iloc[-1, 2])
    bb_percent_b = float(bb.iloc[-1, 4])  # BBP column
    bb_bandwidth = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0.0

    adx_df = ta.adx(high, low, close, length=14)
    adx_val = float(adx_df.iloc[-1, 0])  # ADX_14

    stoch_df = ta.stoch(high, low, close, k=14, d=3)
    stoch_k = float(stoch_df.iloc[-1, 0])
    stoch_d = float(stoch_df.iloc[-1, 1])

    obv_series = ta.obv(close, volume)
    obv_val = float(obv_series.iloc[-1])
    obv_slope = _obv_slope(obv_series, window=20)

    mfi_val = float(ta.mfi(high, low, close, volume, length=14).iloc[-1])

    rsi_series = ta.rsi(close, length=14)
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    macd_line = macd_df.iloc[:, 0]

    rsi_div = _detect_divergence(close, rsi_series, lookback=60)
    macd_div = _detect_divergence(close, macd_line, lookback=60)

    # Weekly resample (Friday close).
    sub_weekly = (
        sub.set_index(pd.to_datetime(sub["date"]))[["close"]]
        .resample("W-FRI").last().dropna()
    )
    if len(sub_weekly) >= 50:
        w_close = sub_weekly["close"].astype(float)
        weekly_ma50 = float(ta.sma(w_close, length=50).iloc[-1])
        weekly_rsi = float(ta.rsi(w_close, length=14).iloc[-1])
        w_last = float(w_close.iloc[-1])
        if w_last > weekly_ma50 and weekly_rsi > 50:
            weekly_trend = "up"
        elif w_last < weekly_ma50 and weekly_rsi < 50:
            weekly_trend = "down"
        else:
            weekly_trend = "neutral"
    else:
        weekly_ma50 = float(close.iloc[-1])
        weekly_rsi = 50.0
        weekly_trend = "neutral"

    last_date = sub["date"].iloc[-1]
    source_date = (
        last_date.date() if hasattr(last_date, "date")
        else pd.Timestamp(last_date).date()
    )

    return ExtendedIndicatorPanel(
        ticker=ticker,
        bb_percent_b=bb_percent_b,
        bb_bandwidth=bb_bandwidth,
        adx=adx_val,
        stoch_k=stoch_k,
        stoch_d=stoch_d,
        obv=obv_val,
        obv_slope_20d=obv_slope,
        mfi=mfi_val,
        rsi_divergence=rsi_div,
        macd_divergence=macd_div,
        weekly_ma50=weekly_ma50,
        weekly_rsi=weekly_rsi,
        weekly_trend=weekly_trend,
        source_date=source_date,
    )
