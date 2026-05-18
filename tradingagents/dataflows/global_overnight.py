"""Global overnight close fetcher — 9 non-US assets via yfinance batch.

이전 분석가들이 안 보는 차원만:
- 미국 데이터는 macro_quant (FRED) + market_risk (VIX/SKEW/sectors)가 커버
- gold는 macro_quant + market_risk 모두 보고 있으므로 여기서 제외
- copper도 macro_quant risk_appetite에 있으므로 제외
"""
import logging
from datetime import date, timedelta

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


GLOBAL_OVERNIGHT_TICKERS: dict[str, dict[str, str]] = {
    "europe": {
        "STOXX50": "^STOXX50E",
        "FTSE":    "^FTSE",
    },
    "asia": {
        "N225": "^N225",
        "HSI":  "^HSI",
        "SSE":  "000001.SS",
        "TWII": "^TWII",
    },
    "commodities": {
        "WTI": "CL=F",
        "NG":  "NG=F",
    },
    "krw": {
        "USDKRW": "KRW=X",
    },
}


def _all_tickers() -> list[str]:
    out: list[str] = []
    for group in GLOBAL_OVERNIGHT_TICKERS.values():
        out.extend(group.values())
    return out


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


def fetch_global_overnight_closes(
    as_of: date, lookback_days: int = 10,
) -> pd.DataFrame:
    """Return DataFrame indexed by date with columns = yfinance tickers.

    빈 DataFrame 반환 시 호출자에서 fallback. 부분 실패는 NaN 컬럼으로 표시.
    """
    symbols = _all_tickers()
    start = as_of - timedelta(days=lookback_days)
    try:
        raw = _raw_yf_batch(symbols, start, as_of)
    except Exception as e:
        logger.warning("Global overnight yfinance batch failed: %s", e)
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
    return closes
