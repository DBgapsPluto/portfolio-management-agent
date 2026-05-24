"""Unit tests for fetcher_yfinance — daily Close + parquet cache."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingagents.backtest.historical.fetcher_yfinance import (
    fetch_yfinance_daily, YFINANCE_TICKERS,
)


def test_yfinance_tickers_include_critical() -> None:
    required = {"^GSPC", "^KS11", "^VIX", "^SKEW",
                "IEF", "TIP", "DJP", "GC=F", "^IRX"}
    assert required.issubset(set(YFINANCE_TICKERS))


def test_fetch_yfinance_daily_uses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw" / "yfinance" / "GSPC.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.Series(
        [400.0, 405.0],
        index=pd.date_range("1991-01-02", periods=2, freq="B"),
        name="^GSPC",
    )
    cached.to_frame("close").to_parquet(cache_path)

    # Request matches cache range — no API call.
    with patch("tradingagents.backtest.historical.fetcher_yfinance._yf_download") as m:
        result = fetch_yfinance_daily(
            "^GSPC", date(1991, 1, 2), date(1991, 1, 3),
            cache_dir=tmp_path / "raw" / "yfinance",
        )
        m.assert_not_called()
    assert len(result) == 2


def test_fetch_yfinance_daily_fetches_on_miss(tmp_path: Path) -> None:
    fake = pd.Series(
        [400.0, 405.0],
        index=pd.date_range("1991-01-02", periods=2, freq="B"),
        name="^GSPC",
    )
    with patch(
        "tradingagents.backtest.historical.fetcher_yfinance._yf_download",
        return_value=fake,
    ):
        result = fetch_yfinance_daily(
            "^GSPC", date(1991, 1, 1), date(1991, 1, 3),
            cache_dir=tmp_path / "raw" / "yfinance",
        )
    assert (tmp_path / "raw" / "yfinance" / "GSPC.parquet").exists()
    assert len(result) == 2
