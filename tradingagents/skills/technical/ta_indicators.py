import pandas as pd
import pandas_ta as ta

from tradingagents.schemas.technical import IndicatorPanel
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_ta_indicators", category="technical")
def compute_ta_indicators(prices: pd.DataFrame, ticker: str) -> IndicatorPanel:
    """Compute MA200/MA50/RSI/MACD/ATR via pandas-ta (pure Python, no C build).

    Args:
        prices: DataFrame with columns [date, open, high, low, close, volume, ticker].
        ticker: Filter for this single ticker.
    """
    sub = prices[prices["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    if len(sub) < 200:
        raise ValueError(f"Need ≥200 data points for {ticker}, got {len(sub)}")

    close = sub["close"].astype(float)
    high = sub["high"].astype(float)
    low = sub["low"].astype(float)

    ma200 = float(ta.sma(close, length=200).iloc[-1])
    ma50 = float(ta.sma(close, length=50).iloc[-1])
    rsi = float(ta.rsi(close, length=14).iloc[-1])

    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    macd_line = float(macd_df.iloc[-1, 0])         # MACD column
    macd_signal_line = float(macd_df.iloc[-1, 2])  # MACDs column
    macd_signal = macd_line - macd_signal_line

    atr = float(ta.atr(high=high, low=low, close=close, length=14).iloc[-1])

    last_date = sub["date"].iloc[-1]
    if hasattr(last_date, "date"):
        source_date = last_date.date()
    else:
        source_date = pd.Timestamp(last_date).date()

    return IndicatorPanel(
        ticker=ticker,
        ma200=ma200, ma50=ma50, rsi=rsi,
        macd_signal=macd_signal, atr=atr,
        source_date=source_date,
    )
