from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series, FRED_SERIES


def test_fetch_yield_returns_pandas():
    fake = pd.Series([4.5, 4.45, 4.4],
                     index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]),
                     name="DGS10")
    with patch("tradingagents.dataflows.fred._raw_fred_call", return_value=fake):
        s = fetch_fred_series("DGS10", date(2026, 5, 8), date(2026, 5, 10), api_key="k")
    assert s.iloc[-1] == 4.4


def test_known_series_constants():
    assert "DGS10" in FRED_SERIES.values()
    assert "CPIAUCSL" in FRED_SERIES.values()
