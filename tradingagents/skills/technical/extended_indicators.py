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


# 2026-05: pandas_ta_classic의 RSI/MFI/Stochastic 등 0-100 bounded indicator가
# IEEE 부동소수점 산술 순서로 100.00000000000001 같은 ε 오버슈트를 반환하는
# 경우가 있음 (특히 합성 데이터 boundary case). schema의 strict bound와 충돌.
# 아래 helper는 tolerance 안의 ε만 흡수하고, 그 밖이면 ValueError로 라이브러리
# 버그를 fail-fast로 노출. 단순 clamp가 라이브러리 버그를 silently 숨기는 것을 방지.
_BOUND_TOL = 0.01
_NEUTRAL_50 = 50.0


def _clamp_bounded(
    val: float, name: str, lo: float = 0.0, hi: float = 100.0,
    on_nan: float = _NEUTRAL_50,
) -> float:
    """Tolerance clamp for [lo, hi] bounded indicators (RSI/MFI/Stoch/ADX).

    - 정상 범위 → 그대로
    - IEEE ε 오버슈트 (≤ _BOUND_TOL) → strict bound로 잘림
    - NaN → on_nan default (보통 50 = neutral). pandas_ta_classic 등이 monotonic
      합성 데이터(real에선 거의 없음)에서 division-by-zero로 NaN 반환할 수 있어
      panel 산출을 통째로 fail 시키지 않고 neutral로 격하.
    - tolerance 밖 → ValueError (라이브러리 진짜 버그 노출).
    """
    import math
    if math.isnan(val):
        return on_nan
    if lo - _BOUND_TOL <= val <= hi + _BOUND_TOL:
        return min(hi, max(lo, val))
    raise ValueError(
        f"{name}={val} outside [{lo}, {hi}] beyond floating-point tolerance "
        f"({_BOUND_TOL}). Underlying TA library may have a bug."
    )


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
    adx_val = _clamp_bounded(float(adx_df.iloc[-1, 0]), "adx")  # ADX_14

    stoch_df = ta.stoch(high, low, close, k=14, d=3)
    stoch_k = _clamp_bounded(float(stoch_df.iloc[-1, 0]), "stoch_k")
    stoch_d = _clamp_bounded(float(stoch_df.iloc[-1, 1]), "stoch_d")

    obv_series = ta.obv(close, volume)
    obv_val = float(obv_series.iloc[-1])
    obv_slope = _obv_slope(obv_series, window=20)

    mfi_val = _clamp_bounded(float(ta.mfi(high, low, close, volume, length=14).iloc[-1]), "mfi")

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
        weekly_rsi = _clamp_bounded(float(ta.rsi(w_close, length=14).iloc[-1]), "weekly_rsi")
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
