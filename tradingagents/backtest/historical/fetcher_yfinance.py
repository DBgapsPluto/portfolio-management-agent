"""yfinance daily Close fetcher — thin wrapper + parquet cache.

Critical: Windows 한글 path 에서 curl_cffi SSL fail (Issue #20). PR2a 는
Linux 환경에서만 fetch — Windows 는 commit 된 parquet cache 만 read.
macOS arm64 smoke test 2026-05-24: PASS (Issue #20 manifest 안 됨).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


YFINANCE_TICKERS: list[str] = [
    # Equity
    "^GSPC",      # S&P 500 (1957+)
    "^KS11",      # KOSPI (1996+)
    # Volatility
    "^VIX",       # CBOE VIX (1990+)
    "^SKEW",      # CBOE SKEW (1990+)
    "^VIX9D",     # CBOE 9-day VIX (2011+, optional)
    # Bond ETFs
    "IEF",        # 7-10y UST (2002+)
    "TIP",        # TIPS (2003+)
    # Commodity / FX proxy
    "DJP",        # iPath Commodity (2006+)
    "GC=F",       # Gold futures (2000+)
    # Cash proxy
    "^IRX",       # 3m T-bill yield (1960+)
    # Sector ETFs — F9 sector_dispersion
    "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLB",
]


def _ticker_to_filename(ticker: str) -> str:
    """Convert ticker for filesystem (^GSPC → GSPC, GC=F → GC_F)."""
    return ticker.replace("^", "").replace("=", "_")


def _yf_download(ticker: str, start: date, end: date) -> pd.Series:
    """yfinance Close, daily. 실패 시 빈 시리즈 반환 (Linux only safe)."""
    import yfinance as yf
    df = yf.download(
        ticker, start=start, end=end + timedelta(days=1),
        auto_adjust=True, progress=False, threads=False,
    )
    if df.empty:
        return pd.Series(dtype=float, name=ticker)
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].iloc[:, 0]
    else:
        close = df["Close"]
    close.index = pd.to_datetime(close.index)
    if close.index.tz is not None:
        close = close.tz_localize(None)
    close.name = ticker
    return close


def fetch_yfinance_daily(
    ticker: str,
    start: date,
    end: date,
    cache_dir: Path | str,
) -> pd.Series:
    """yfinance daily Close with parquet cache."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{_ticker_to_filename(ticker)}.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        series = df["close"]
        series.name = ticker
        if (not series.empty and
                series.index.min().date() <= start and
                series.index.max().date() >= end):
            logger.debug("yfinance %s: cache hit (%s rows)", ticker, len(series))
            return series.loc[start:end]
        logger.info("yfinance %s: cache stale, refetching", ticker)

    series = _yf_download(ticker, start, end)
    series.to_frame("close").to_parquet(cache_path)
    logger.info("yfinance %s: fetched %s rows, cached", ticker, len(series))
    return series
