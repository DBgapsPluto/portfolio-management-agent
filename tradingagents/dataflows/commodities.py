"""Commodity price fetcher via yfinance. Used for cross-asset risk-on/off proxies."""
import logging
from datetime import date, timedelta

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


COMMODITY_TICKERS = {
    "copper": "HG=F",   # COMEX copper futures, USD/lb
    "gold": "GC=F",     # COMEX gold futures, USD/oz
    "wti_oil": "CL=F",  # WTI crude futures, USD/bbl (future use)
    "brent_oil": "BZ=F",
}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_yf_history(symbol: str, start: date, end: date) -> pd.DataFrame:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    df = ticker.history(
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=True,
    )
    if df is not None and not df.empty and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_commodity_close(
    name: str, start: date, end: date,
) -> pd.Series:
    """Fetch daily close price for a commodity by friendly name.

    Returns pd.Series indexed by datetime, name = friendly_name.
    Empty Series on failure (caller should fallback).
    """
    if name not in COMMODITY_TICKERS:
        raise KeyError(f"unknown commodity: {name!r}")
    symbol = COMMODITY_TICKERS[name]
    df = _raw_yf_history(symbol, start, end)
    if df is None or df.empty or "Close" not in df.columns:
        return pd.Series(dtype=float, name=name)
    s = df["Close"].copy()
    s.name = name
    return s
