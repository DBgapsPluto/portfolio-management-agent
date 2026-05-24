"""Unit tests for fetcher_alfred — vintage-aware FRED fetch (Critical 1)."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingagents.backtest.historical.fetcher_alfred import (
    fetch_alfred_vintage_quarterly, ALFRED_SERIES,
)


def test_alfred_series_lists_7_revising() -> None:
    """7 revising series — Critical 1. CFNAI (not CFNAINMNI — does not exist in ALFRED)."""
    assert set(ALFRED_SERIES) == {
        "CFNAI", "NFCI", "ANFCI", "GDPNOW",
        "UNRATE", "CPIAUCSL", "PCEPILFE",
    }


def test_fetch_alfred_vintage_uses_cache(tmp_path: Path) -> None:
    """Cache hit → API call 없음."""
    cache_path = tmp_path / "raw" / "fred_alfred" / "CFNAI.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.DataFrame({
        "vintage_value": [-0.3, -0.2, -0.1],
    }, index=pd.to_datetime(["1991-03-31", "1991-06-30", "1991-09-30"]))
    cached.to_parquet(cache_path)

    # Request matches cached range — cache covers it → no API call.
    with patch("tradingagents.backtest.historical.fetcher_alfred._call_alfred") as m:
        result = fetch_alfred_vintage_quarterly(
            "CFNAI", date(1991, 3, 31), date(1991, 9, 30),
            cache_dir=tmp_path / "raw" / "fred_alfred",
        )
        m.assert_not_called()
    assert len(result) == 3
    assert result["vintage_value"].iloc[0] == -0.3


def test_fetch_alfred_vintage_fetches_per_quarter(tmp_path: Path) -> None:
    """Cache miss → 각 quarter end 별 ALFRED API call → parquet 저장."""
    def fake_call(series_id, realtime_date):
        # Return vintage value at realtime_date — fake non-revised value.
        # Intent: Q1 & Q2 → -0.5, Q3 → -0.3 (inclusive boundary).
        return -0.5 if realtime_date <= date(1991, 6, 30) else -0.3
    with patch(
        "tradingagents.backtest.historical.fetcher_alfred._call_alfred",
        side_effect=fake_call,
    ) as m:
        result = fetch_alfred_vintage_quarterly(
            "CFNAI", date(1991, 3, 31), date(1991, 9, 30),
            cache_dir=tmp_path / "raw" / "fred_alfred",
        )
        assert m.call_count == 3  # 3 quarters: 1991-Q1, Q2, Q3
    assert (tmp_path / "raw" / "fred_alfred" / "CFNAI.parquet").exists()
    assert list(result["vintage_value"]) == [-0.5, -0.5, -0.3]
