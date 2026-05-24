"""Unit tests for bucket_returns — KRW basis 5-bucket quarterly."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.historical.bucket_returns import (
    compute_bucket_returns_quarterly, BUCKETS_5,
)


def test_buckets_5_are_correct() -> None:
    assert BUCKETS_5 == ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf")


def test_compute_global_equity_krw_translation(tmp_path: Path) -> None:
    """SPX 10% USD return + KRW 10% depreciation → 21% KRW basis return."""
    raw = tmp_path / "raw"
    yf_dir = raw / "yfinance"
    yf_dir.mkdir(parents=True)
    fred_dir = raw / "fred"
    fred_dir.mkdir(parents=True)

    # 2 quarter-end points: SPX 4000 → 4400 (USD +10%)
    spx = pd.Series(
        [4000.0, 4400.0],
        index=pd.to_datetime(["2010-03-31", "2010-06-30"]),
    )
    spx.to_frame("close").to_parquet(yf_dir / "GSPC.parquet")

    # USDKRW: 1200 → 1320 (KRW depreciates 10%)
    usdkrw = pd.Series(
        [1200.0, 1320.0],
        index=pd.to_datetime(["2010-03-31", "2010-06-30"]),
    )
    usdkrw.to_frame("value").to_parquet(fred_dir / "DEXKOUS.parquet")

    returns = compute_bucket_returns_quarterly(
        start=date(2010, 3, 31), end=date(2010, 6, 30),
        raw_dir=raw, basis="KRW",
    )
    # global_equity quarterly return at 2010-06-30 = (1+0.10)(1+0.10) - 1 = 0.21
    assert returns.loc["2010-06-30", "global_equity"] == pytest.approx(0.21, rel=1e-3)


def test_pre_1996_kr_equity_is_nan(tmp_path: Path) -> None:
    """KOSPI 1996+ only. 1991-1995 의 kr_equity = NaN."""
    raw = tmp_path / "raw"
    (raw / "yfinance").mkdir(parents=True)
    (raw / "fred").mkdir(parents=True)
    # No KOSPI cache file → kr_equity empty → result column = NaN
    # Provide DGS10 + USDKRW minimal so other buckets compute
    pd.Series([6.0, 6.0], index=pd.to_datetime(["1991-03-31", "1991-06-30"])).to_frame(
        "value").to_parquet(raw / "fred" / "DGS10.parquet")
    pd.Series([700.0, 700.0], index=pd.to_datetime(["1991-03-31", "1991-06-30"])).to_frame(
        "value").to_parquet(raw / "fred" / "DEXKOUS.parquet")

    returns = compute_bucket_returns_quarterly(
        start=date(1991, 3, 31), end=date(1991, 6, 30),
        raw_dir=raw, basis="KRW",
    )
    assert pd.isna(returns.loc["1991-06-30", "kr_equity"])
