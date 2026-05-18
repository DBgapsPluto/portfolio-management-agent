"""Equity index price fetcher via yfinance.

Used for tail-risk/sentiment indices that FRED does not host
(CBOE SKEW, etc.).
"""
import logging
from datetime import date, timedelta

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


EQUITY_INDEX_TICKERS = {
    "skew": "^SKEW",        # CBOE SKEW Index
    "vix_alt": "^VIX",      # VIX backup (when FRED VIXCLS is stale)
    "vxn_alt": "^VXN",      # VXN backup
    "rut": "^RUT",          # Russell 2000 (future breadth use)
    "ndx": "^NDX",          # NASDAQ-100 (future use)
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
        auto_adjust=False,
    )
    if df is not None and not df.empty and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def fetch_equity_index_close(
    name: str, start: date, end: date,
) -> pd.Series:
    """Fetch daily close for an equity index by friendly name.

    Returns pd.Series indexed by datetime. Empty Series on failure.
    """
    if name not in EQUITY_INDEX_TICKERS:
        raise KeyError(f"unknown equity index: {name!r}")
    symbol = EQUITY_INDEX_TICKERS[name]
    df = _raw_yf_history(symbol, start, end)
    if df is None or df.empty or "Close" not in df.columns:
        return pd.Series(dtype=float, name=name)
    s = df["Close"].copy()
    s.name = name
    return s
