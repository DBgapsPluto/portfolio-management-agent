"""Unit tests for aggregate.py — daily/monthly → quarterly panel + derived."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.historical.aggregate import (
    daily_to_quarter_end_last,
    derive_yoy_pct,
    derive_3mo_annualized,
    derive_rolling_vol_pct,
    derive_yield_spread_bps,
    derive_3mo_avg,
    derive_sector_dispersion,
    derive_vrp_pct,
    assemble_quarterly_panel,
)


def test_daily_to_quarter_end_last_picks_last_trading_day() -> None:
    """resample('QE').last() picks last present value within quarter."""
    daily = pd.Series(
        [10.0, 11.0, 12.0],
        index=pd.to_datetime(["1991-03-28", "1991-03-29", "1991-04-01"]),
    )
    q = daily_to_quarter_end_last(daily)
    # quarter 1991-Q1 의 last entry = 1991-03-29 (value 11.0)
    assert q.loc["1991-03-31"] == 11.0


def test_derive_yoy_pct_basic() -> None:
    monthly = pd.Series(
        np.arange(1, 25, dtype=float),
        index=pd.date_range("1990-01-31", periods=24, freq="ME"),
    )
    yoy = derive_yoy_pct(monthly)
    assert yoy.loc["1991-01-31"] == pytest.approx(1200.0)


def test_derive_3mo_annualized_basic() -> None:
    monthly = pd.Series(
        [100.0, 101.0, 102.0, 103.0],
        index=pd.date_range("1990-01-31", periods=4, freq="ME"),
    )
    ann = derive_3mo_annualized(monthly)
    expected = ((103.0 / 100.0) ** 4 - 1) * 100
    assert ann.iloc[-1] == pytest.approx(expected, rel=1e-3)


def test_derive_rolling_vol_pct_annualized() -> None:
    """daily returns std × sqrt(252) × 100."""
    flat = pd.Series([100.0] * 100, index=pd.date_range("1990-01-01", periods=100, freq="B"))
    vol = derive_rolling_vol_pct(flat, window=60)
    assert vol.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_derive_yield_spread_bps_handles_nan_gap() -> None:
    """DGS30 의 2002-2006 gap 의 경우 spread = NaN."""
    s30 = pd.Series(
        [3.0, np.nan, 4.0],
        index=pd.to_datetime(["2001-12-31", "2003-12-31", "2007-12-31"]),
    )
    s5 = pd.Series(
        [2.5, 2.7, 3.5],
        index=pd.to_datetime(["2001-12-31", "2003-12-31", "2007-12-31"]),
    )
    spread = derive_yield_spread_bps(s30, s5)
    assert spread.iloc[0] == pytest.approx(50.0)
    assert pd.isna(spread.iloc[1])
    assert spread.iloc[2] == pytest.approx(50.0)


def test_derive_3mo_avg() -> None:
    monthly = pd.Series(
        [1.0, 2.0, 3.0, 4.0],
        index=pd.date_range("1990-01-31", periods=4, freq="ME"),
    )
    avg = derive_3mo_avg(monthly, window=3)
    assert avg.iloc[-1] == pytest.approx(3.0)


def test_derive_sector_dispersion_with_partial_sectors() -> None:
    """9 sector ETF daily Close → quarterly std of 60d returns dispersion."""
    sectors = {
        "XLE": pd.Series([100.0] * 100, index=pd.date_range("2010-01-04", periods=100, freq="B")),
        "XLF": pd.Series(np.linspace(100, 110, 100), index=pd.date_range("2010-01-04", periods=100, freq="B")),
    }
    disp = derive_sector_dispersion(sectors, window=60)
    assert disp.iloc[-1] > 0


def test_derive_vrp_pct_basic() -> None:
    """VRP = (VIX/100)^2 - realized_vol_60d^2."""
    vix = pd.Series([20.0, 25.0], index=pd.date_range("2010-01-01", periods=2, freq="QE"))
    rv60 = pd.Series([15.0, 18.0], index=pd.date_range("2010-01-01", periods=2, freq="QE"))
    vrp = derive_vrp_pct(vix, rv60)
    assert vrp.iloc[0] == pytest.approx(0.04 - 0.0225, rel=1e-3)


def test_assemble_quarterly_panel_basic_structure(tmp_path: Path) -> None:
    """Mocked raw fetch → quarterly panel with expected columns."""
    raw_dir = tmp_path / "raw"
    fred_dir = raw_dir / "fred"
    fred_dir.mkdir(parents=True)
    # Stub DGS10 (daily)
    dgs10 = pd.Series(
        np.linspace(2.0, 3.0, 100),
        index=pd.date_range("1991-01-01", periods=100, freq="B"),
    )
    dgs10.to_frame("value").to_parquet(fred_dir / "DGS10.parquet")
    # Stub DGS2 (daily) for spread
    dgs2 = pd.Series(
        np.linspace(1.5, 2.5, 100),
        index=pd.date_range("1991-01-01", periods=100, freq="B"),
    )
    dgs2.to_frame("value").to_parquet(fred_dir / "DGS2.parquet")

    panel = assemble_quarterly_panel(
        start=date(1991, 1, 1), end=date(1991, 6, 30),
        raw_dir=raw_dir,
    )
    assert isinstance(panel, pd.DataFrame)
    assert panel.index.name == "quarter_end"
    # 빈 panel 도 columns 구조는 유지
    assert "dgs10_pct" in panel.columns
    assert "spread_10y_2y_bps" in panel.columns
