from datetime import date

import pandas as pd

from tradingagents.dataflows.pykrx_data import fetch_etf_ohlcv_batch, ParquetCache
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_etf_price_batch", category="technical")
def fetch_etf_price_batch(
    tickers: list[str], start: date, end: date, cache_path: str | None = None,
) -> pd.DataFrame:
    cache = ParquetCache(cache_path) if cache_path else None
    return fetch_etf_ohlcv_batch(tickers, start, end, cache=cache)
