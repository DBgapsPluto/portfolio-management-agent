from datetime import date
from unittest.mock import patch
import pandas as pd

from tradingagents.skills.technical.price_batch import fetch_etf_price_batch


def test_price_batch_wraps_dataflow():
    fake = pd.DataFrame({
        "ticker": ["A069500"],
        "date": [pd.Timestamp("2026-05-10")],
        "open": [100], "high": [110], "low": [99], "close": [105], "volume": [1000],
    })
    with patch("tradingagents.skills.technical.price_batch.fetch_etf_ohlcv_batch",
               return_value=fake):
        df = fetch_etf_price_batch(["A069500"], date(2026, 5, 10), date(2026, 5, 10))
    assert len(df) == 1
    assert df["ticker"].iloc[0] == "A069500"
