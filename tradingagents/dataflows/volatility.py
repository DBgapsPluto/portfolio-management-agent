from datetime import date

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series


VKOSPI_INDEX_CODE = "1037"  # KRX VKOSPI 지수 코드


def fetch_vix(start: date, end: date, api_key: str | None = None) -> pd.Series:
    """VIX from FRED (VIXCLS)."""
    return fetch_fred_series("vix_close", start, end, api_key=api_key)


def _raw_pykrx_index_call(code: str, start: date, end: date) -> pd.DataFrame:
    """Direct pykrx index call. Wrapped for mocking."""
    from pykrx import stock
    return stock.get_index_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)


def _live_vkospi(start: date, end: date) -> pd.Series:
    try:
        df = _raw_pykrx_index_call(VKOSPI_INDEX_CODE, start, end)
        if df is None or df.empty or "종가" not in df.columns:
            return pd.Series(dtype=float, name="VKOSPI")
        return df["종가"].rename("VKOSPI")
    except Exception:
        return pd.Series(dtype=float, name="VKOSPI")


def fetch_vkospi(
    start: date, end: date,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.Series:
    """VKOSPI close from KRX via pykrx. Empty Series on any failure.

    KRX의 일부 지수 endpoint(VKOSPI 포함)는 KRX_ID/KRX_PW 환경 변수가 있어야
    완전히 동작. 자격증명이 없으면 pykrx가 빈 JSON을 받아 KeyError 발생하지만
    graceful degradation으로 빈 Series 반환.

    Cache: ~/.tradingagents/cache/pykrx_index/vkospi/{end}.json
    """
    if not use_cache:
        return _live_vkospi(start, end)

    from tradingagents.dataflows.series_cache import fetch_series_with_cache
    try:
        return fetch_series_with_cache(
            lambda: _live_vkospi(start, end),
            namespace="pykrx_index",
            cache_key="vkospi",
            as_of=end,
            max_staleness=max_staleness,
        )
    except Exception:
        return pd.Series(dtype=float, name="VKOSPI")
