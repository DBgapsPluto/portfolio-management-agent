from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.dataflows.volatility import fetch_vix, fetch_vkospi


def test_fetch_vix_returns_close_series():
    fake = pd.Series([18.5, 19.0, 18.7],
                     index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]),
                     name="VIXCLS")
    with patch("tradingagents.dataflows.fred._raw_fred_call", return_value=fake):
        s = fetch_vix(date(2026, 5, 8), date(2026, 5, 10), api_key="x")
    assert s.iloc[-1] == 18.7


def test_fetch_vkospi_krx_openapi():
    # _live_vkospi parses the KRX OpenAPI drvprod series (date-str -> value dict).
    # (The old pykrx get_index_ohlcv(1037) path was removed 2026-06-03 — KRX
    # dropped index 1037; this test mocks the live KRX OpenAPI source instead.)
    fake = {"20260508": 21.0, "20260509": 22.5, "20260510": 20.8}
    with patch("tradingagents.dataflows.krx_openapi.fetch_index_series",
               return_value=fake):
        s = fetch_vkospi(date(2026, 5, 8), date(2026, 5, 10), use_cache=False)
    assert len(s) == 3
    assert s.iloc[-1] == 20.8


def test_fetch_vkospi_empty_on_failure():
    # KRX OpenAPI returns nothing -> empty Series (caller falls back to sentinel).
    with patch("tradingagents.dataflows.krx_openapi.fetch_index_series",
               return_value={}):
        s = fetch_vkospi(date(2026, 5, 8), date(2026, 5, 10), use_cache=False)
    assert s.empty
