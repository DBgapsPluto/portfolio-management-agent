from datetime import date

import pandas as pd

from tradingagents.dataflows.pykrx_data import fetch_etf_ohlcv_batch, ParquetCache
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_returns_matrix", category="portfolio")
def fetch_returns_matrix(
    tickers: list[str], start: date, end: date, cache_path: str | None = None,
) -> pd.DataFrame:
    """Fetch close prices and compute daily returns matrix (date × ticker)."""
    cache = ParquetCache(cache_path) if cache_path else None
    raw = fetch_etf_ohlcv_batch(tickers, start, end, cache=cache)
    if raw.empty:
        return pd.DataFrame()

    pivot = raw.pivot(index="date", columns="ticker", values="close")
    returns = pivot.pct_change().dropna(how="all")
    return returns
