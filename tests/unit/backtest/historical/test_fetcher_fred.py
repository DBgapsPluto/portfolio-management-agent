"""Unit tests for fetcher_fred — thin wrapper + parquet cache."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.backtest.historical.fetcher_fred import (
    fetch_fred_latest, FRED_QUARTERLY_SERIES,
)


def test_fetch_fred_latest_uses_cache_if_available(tmp_path: Path) -> None:
    """Cache 가 있으면 FRED API call 없이 parquet 에서 read."""
    cache_path = tmp_path / "raw" / "fred" / "DGS10.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.Series(
        [3.0, 3.1, 3.2], index=pd.date_range("1991-01-01", periods=3, freq="D"),
        name="DGS10",
    )
    cached.to_frame("value").to_parquet(cache_path)

    with patch("tradingagents.backtest.historical.fetcher_fred.fetch_fred_series") as m:
        result = fetch_fred_latest("DGS10", date(1991, 1, 1), date(1991, 1, 3),
                                    cache_dir=tmp_path / "raw" / "fred")
        m.assert_not_called()
    assert len(result) == 3
    assert result.iloc[0] == 3.0


def test_fetch_fred_latest_fetches_and_caches_on_miss(tmp_path: Path) -> None:
    """Cache miss → fetch_fred_series 호출 → parquet 저장."""
    fake_series = pd.Series(
        [4.0, 4.1], index=pd.date_range("1991-01-01", periods=2, freq="D"),
        name="DGS10",
    )
    with patch(
        "tradingagents.backtest.historical.fetcher_fred.fetch_fred_series",
        return_value=fake_series,
    ) as m:
        result = fetch_fred_latest("DGS10", date(1991, 1, 1), date(1991, 1, 2),
                                    cache_dir=tmp_path / "raw" / "fred")
        m.assert_called_once()

    assert (tmp_path / "raw" / "fred" / "DGS10.parquet").exists()
    assert len(result) == 2


def test_fred_quarterly_series_includes_critical_indicators() -> None:
    """C1-C4 의 modeled indicator 가 series map 에 등록."""
    required = {"DGS10", "DGS2", "DGS5", "DGS30", "CPIAUCSL", "PCEPILFE",
                "DFII10", "DEXKOUS", "DTWEXM", "BAA", "AAA", "BAA10Y", "MICH",
                "T5YIFR", "VIXCLS", "UNRATE", "TB3MS"}
    assert required.issubset(set(FRED_QUARTERLY_SERIES))
