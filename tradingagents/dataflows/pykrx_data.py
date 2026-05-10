import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_pykrx_call(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Direct pykrx call. Wrapped for mocking + retry on transient failures."""
    from pykrx import stock
    return stock.get_market_ohlcv(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker
    )


def fetch_etf_ohlcv(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch one ETF's OHLCV. Returns columns [open, high, low, close, volume, ticker, date]."""
    raw = _raw_pykrx_call(ticker, start, end)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    rename = {
        "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume",
    }
    df = raw.rename(columns=rename)[["open", "high", "low", "close", "volume"]]
    df["ticker"] = ticker
    df.index.name = "date"
    return df.reset_index()


class ParquetCache:
    """Parquet-backed price cache for ETF OHLCV (D10)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
        return pd.read_parquet(self.path)

    def has(self, ticker: str, start: date, end: date) -> bool:
        df = self.read()
        if df.empty:
            return False
        sub = df[df["ticker"] == ticker]
        if sub.empty:
            return False
        sub_dates = pd.to_datetime(sub["date"]).dt.date
        return sub_dates.min() <= start and sub_dates.max() >= end

    def write_append(self, new_data: pd.DataFrame) -> None:
        existing = self.read()
        merged = pd.concat([existing, new_data], ignore_index=True)
        merged = merged.drop_duplicates(subset=["ticker", "date"], keep="last")
        merged.to_parquet(self.path, index=False)


def fetch_etf_ohlcv_batch(
    tickers: list[str],
    start: date,
    end: date,
    cache: ParquetCache | None = None,
) -> pd.DataFrame:
    """Fetch multiple ETFs' OHLCV (time-series, ticker-by-ticker)."""
    frames: list[pd.DataFrame] = []
    for t in tickers:
        if cache is not None and cache.has(t, start, end):
            cached = cache.read()
            sub = cached[cached["ticker"] == t]
            sub_dates = pd.to_datetime(sub["date"]).dt.date
            mask = (sub_dates >= start) & (sub_dates <= end)
            frames.append(sub[mask][["ticker", "date", "open", "high", "low", "close", "volume"]])
            continue
        df = fetch_etf_ohlcv(t, start, end)
        if not df.empty and cache is not None:
            cache.write_append(df)
        frames.append(df[["ticker", "date", "open", "high", "low", "close", "volume"]])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_pykrx_snapshot_call(target_date: date) -> pd.DataFrame:
    """Direct pykrx snapshot call — all ETFs on a single date in one shot."""
    from pykrx import stock
    return stock.get_etf_ohlcv_by_ticker(target_date.strftime("%Y%m%d"))


def fetch_etf_snapshot_by_date(
    target_date: date, cache: ParquetCache | None = None,
) -> pd.DataFrame:
    """One pykrx call returns OHLCV for ALL KRX-listed ETFs on target_date."""
    raw = _raw_pykrx_snapshot_call(target_date)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])

    df = raw.reset_index().rename(columns={
        "티커": "ticker", "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume",
    })
    df["date"] = pd.Timestamp(target_date)
    df = df[["ticker", "date", "open", "high", "low", "close", "volume"]]
    if cache is not None:
        cache.write_append(df)
    return df
