from datetime import date
from unittest.mock import patch
import pandas as pd

from tradingagents.skills.risk.credit_spread import fetch_credit_spread


def test_credit_spread_us_hy():
    fake = pd.Series([2.5, 3.0, 3.5, 4.0] * 100,
                     index=pd.date_range("2024-01-01", periods=400))
    with patch("tradingagents.skills.risk.credit_spread.fetch_fred_series",
               return_value=fake):
        snap = fetch_credit_spread("US_HY", date(2026, 5, 10), api_key="k")
    assert snap.region == "US_HY"
    assert snap.current_bps > 0
