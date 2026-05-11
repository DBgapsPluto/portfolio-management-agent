from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.pykrx_data import (
    fetch_etf_ohlcv, fetch_etf_ohlcv_batch, ParquetCache,
)


@pytest.fixture
def fake_pykrx_response():
    return pd.DataFrame({
        "시가": [40000, 40100, 40200],
        "고가": [40500, 40400, 40400],
        "저가": [39800, 39900, 40000],
        "종가": [40200, 40150, 40300],
        "거래량": [100000, 110000, 105000],
    }, index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]))


def test_fetch_single_etf(fake_pykrx_response):
    with patch("tradingagents.dataflows.pykrx_data._raw_pykrx_call",
               return_value=fake_pykrx_response):
        df = fetch_etf_ohlcv("A069500", date(2026, 5, 8), date(2026, 5, 10))
    assert "close" in df.columns
    assert len(df) == 3
    assert df["close"].iloc[0] == 40200


def test_raw_pykrx_call_strips_A_prefix():
    """universe.json uses 'A069500'; pykrx requires '069500'. Verify normalization."""
    from tradingagents.dataflows import pykrx_data

    captured = {}

    class _FakeStock:
        @staticmethod
        def get_market_ohlcv(start, end, ticker):
            captured["ticker"] = ticker
            return pd.DataFrame()  # empty fine; just capturing args

    import sys
    fake_module = type(sys)("pykrx_fake")
    fake_module.stock = _FakeStock
    with patch.dict("sys.modules", {"pykrx": fake_module}):
        pykrx_data._raw_pykrx_call("A069500", date(2026, 5, 1), date(2026, 5, 2))
    assert captured["ticker"] == "069500"

    # No-prefix ticker should pass through unchanged
    captured.clear()
    with patch.dict("sys.modules", {"pykrx": fake_module}):
        pykrx_data._raw_pykrx_call("069500", date(2026, 5, 1), date(2026, 5, 2))
    assert captured["ticker"] == "069500"


def test_batch_fetch_uses_cache(tmp_path, fake_pykrx_response):
    cache = ParquetCache(tmp_path / "etf.parquet")
    tickers = ["A069500", "A360750"]

    with patch("tradingagents.dataflows.pykrx_data._raw_pykrx_call",
               return_value=fake_pykrx_response) as mock_call:
        df1 = fetch_etf_ohlcv_batch(tickers, date(2026, 5, 8), date(2026, 5, 10), cache=cache)
        df2 = fetch_etf_ohlcv_batch(tickers, date(2026, 5, 8), date(2026, 5, 10), cache=cache)

    assert mock_call.call_count == 2
    assert len(df1) == 6
    assert df1.equals(df2)
