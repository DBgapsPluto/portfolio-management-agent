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


def fetch_cross_asset_returns(
    start: date, end: date, tickers: list[str] | None = None,
) -> pd.DataFrame:
    """5-asset 일별 returns DataFrame (rows=date, cols=ticker).

    실패 시 빈 DataFrame 반환 → 분석가에서 fallback 처리.
    """
    symbols = tickers or CROSS_ASSET_TICKERS
    try:
        raw = _raw_yf_batch(symbols, start, end)
    except Exception as e:
        logger.warning("Cross-asset yfinance batch failed: %s", e)
        return pd.DataFrame()

    if raw is None or raw.empty:
        return pd.DataFrame()

    # MultiIndex 처리 (yfinance가 ("Close", ticker) 형식으로 반환)
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            closes = raw["Close"]
        elif "Adj Close" in raw.columns.get_level_values(0):
            closes = raw["Adj Close"]
        else:
            return pd.DataFrame()
    else:
        # 단일 ticker 또는 simple columns
        closes = raw[["Close"]] if "Close" in raw.columns else raw

    closes = closes.dropna(how="all")
    if closes.empty or len(closes) < 2:
        return pd.DataFrame()

    returns = closes.pct_change().dropna(how="all")
    return returns
