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


def test_fetch_vkospi_pykrx():
    fake_df = pd.DataFrame({
        "종가": [21.0, 22.5, 20.8],
    }, index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]))
    with patch("tradingagents.dataflows.volatility._raw_pykrx_index_call",
               return_value=fake_df):
        s = fetch_vkospi(date(2026, 5, 8), date(2026, 5, 10))
    assert s.iloc[-1] == 20.8
