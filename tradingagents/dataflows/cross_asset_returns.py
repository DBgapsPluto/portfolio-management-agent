"""Cross-asset 일별 returns matrix fetcher for PCA / correlation analysis.

Tier-4: 기존 synthetic 4-asset data를 실제 yfinance 데이터로 교체.
5개 자산:
- SPY: US large-cap equity
- QQQ: US tech (NASDAQ-100)
- TLT: US 20y Treasury bond ETF
- GLD: Gold ETF
- EWY: iShares MSCI South Korea (KOSPI proxy)
"""
import logging
from datetime import date, timedelta

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


CROSS_ASSET_TICKERS = ["SPY", "QQQ", "TLT", "GLD", "EWY"]


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_yf_batch(symbols: list[str], start: date, end: date) -> pd.DataFrame:
    import yfinance as yf
    raw = yf.download(
        " ".join(symbols),
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
        auto_adjust=True, progress=False, group_by="column",
    )
    return raw


def _live_cross_asset_returns(
    start: date, end: date, tickers: list[str] | None = None,
) -> pd.DataFrame:
    symbols = tickers or CROSS_ASSET_TICKERS
    try:
        raw = _raw_yf_batch(symbols, start, end)
    except Exception as e:
        logger.warning("Cross-asset yfinance batch failed: %s", e)
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            closes = raw["Close"]
        elif "Adj Close" in raw.columns.get_level_values(0):
            closes = raw["Adj Close"]
        else:
            return pd.DataFrame()
    else:
        closes = raw[["Close"]] if "Close" in raw.columns else raw

    closes = closes.dropna(how="all")
    if closes.empty or len(closes) < 2:
        return pd.DataFrame()

    return closes.pct_change().dropna(how="all")


def fetch_cross_asset_returns(
    start: date, end: date, tickers: list[str] | None = None,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.DataFrame:
    """5-asset 일별 returns DataFrame (rows=date, cols=ticker).

    Cache: ~/.tradingagents/cache/cross_asset/{symbols_hash}/{end}.json
    실패 시 빈 DataFrame 반환 → 분석가에서 fallback 처리.
    """
    if not use_cache:
        return _live_cross_asset_returns(start, end, tickers)

    symbols = tickers or CROSS_ASSET_TICKERS
    cache_key = "_".join(sorted(symbols))
    if len(cache_key) > 80:
        # 너무 긴 ticker set은 hash로 압축
        import hashlib
        cache_key = hashlib.sha1(cache_key.encode()).hexdigest()[:16]

    from tradingagents.dataflows.series_cache import fetch_frame_with_cache
    try:
        return fetch_frame_with_cache(
            lambda: _live_cross_asset_returns(start, end, tickers),
            namespace="cross_asset",
            cache_key=cache_key,
            as_of=end,
            max_staleness=max_staleness,
        )
    except Exception as e:
        logger.warning("cross_asset cache+live both failed: %s", e)
        return pd.DataFrame()
