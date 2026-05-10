from datetime import date
from unittest.mock import patch
import pandas as pd

from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix


def test_returns_matrix_pivots_and_pct_change():
    fake = pd.DataFrame({
        "ticker": ["A1"]*3 + ["A2"]*3,
        "date": pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]*2),
        "close": [100.0, 101.0, 102.0, 200.0, 198.0, 202.0],
    })
    with patch("tradingagents.skills.portfolio.returns_matrix.fetch_etf_ohlcv_batch",
               return_value=fake):
        ret = fetch_returns_matrix(["A1", "A2"], date(2026, 5, 8), date(2026, 5, 10))
    assert "A1" in ret.columns
    assert "A2" in ret.columns
    assert len(ret) >= 1  # pct_change drops first row
