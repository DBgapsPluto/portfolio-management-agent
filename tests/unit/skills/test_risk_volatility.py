from datetime import date
from unittest.mock import patch
import pandas as pd

from tradingagents.skills.risk.volatility import fetch_volatility_index


def test_vix_snapshot():
    fake = pd.Series([18.0, 18.5, 19.0, 18.8, 18.2] * 30,
                     index=pd.date_range("2026-01-01", periods=150))
    with patch("tradingagents.skills.risk.volatility.fetch_vix", return_value=fake):
        snap = fetch_volatility_index("VIX", date(2026, 5, 10))
    assert snap.index_name == "VIX"
    assert snap.current_value > 0
