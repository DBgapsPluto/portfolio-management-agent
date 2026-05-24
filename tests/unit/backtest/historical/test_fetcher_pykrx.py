"""Unit tests for fetcher_pykrx — KOSPI200 valuation + foreign flow."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingagents.backtest.historical.fetcher_pykrx import (
    fetch_kospi200_valuation_monthly,
    fetch_foreign_flow_monthly,
)


def test_fetch_kospi200_valuation_uses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw" / "pykrx" / "kospi200_valuation.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.DataFrame({
        "PBR": [1.1, 1.2],
        "PER": [15.0, 16.0],
        "DIV_YIELD": [2.0, 2.1],
    }, index=pd.to_datetime(["2010-01-31", "2010-02-28"]))
    cached.to_parquet(cache_path)

    # Request matches cache range.
    with patch("tradingagents.backtest.historical.fetcher_pykrx._pykrx_fundamental_call") as m:
        result = fetch_kospi200_valuation_monthly(
            date(2010, 1, 31), date(2010, 2, 28),
            cache_dir=tmp_path / "raw" / "pykrx",
        )
        m.assert_not_called()
    assert len(result) == 2
    assert "PBR" in result.columns


def test_fetch_foreign_flow_uses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw" / "pykrx" / "foreign_flow.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.DataFrame({
        "net_buy_krw": [100.0, -50.0],
    }, index=pd.to_datetime(["2010-01-31", "2010-02-28"]))
    cached.to_parquet(cache_path)

    with patch("tradingagents.backtest.historical.fetcher_pykrx._pykrx_foreign_call") as m:
        result = fetch_foreign_flow_monthly(
            date(2010, 1, 31), date(2010, 2, 28),
            cache_dir=tmp_path / "raw" / "pykrx",
        )
        m.assert_not_called()
    assert len(result) == 2
