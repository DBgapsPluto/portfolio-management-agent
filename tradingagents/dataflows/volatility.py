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


def fetch_vkospi(start: date, end: date) -> pd.Series:
    """VKOSPI close from KRX via pykrx."""
    df = _raw_pykrx_index_call(VKOSPI_INDEX_CODE, start, end)
    return df["종가"].rename("VKOSPI")
