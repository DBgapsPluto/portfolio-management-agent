"""Unit tests for regime.py — NBER classifier + sample split."""
from datetime import date

import pandas as pd
import pytest

from tradingagents.backtest.regime import (
    nber_recession_quarterly_from_series,
    split_samples_by_regime,
)
from tradingagents.skills.research.factor_calibration import HistoricalSample


def test_nber_recession_quarterly_from_monthly_series() -> None:
    """monthly USREC → quarterly (any month=1 in quarter → recession=True).

    2008-Q4 / 2009-Q1 / 2009-Q2 = recession (1), 2009-Q3 = expansion (0).
    """
    monthly = pd.Series(
        [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0],
        index=pd.date_range("2008-10-01", periods=12, freq="MS"),
        name="USREC",
    )
    q = nber_recession_quarterly_from_series(monthly)
    assert q.loc["2008-12-31"] == True
    assert q.loc["2009-03-31"] == True
    assert q.loc["2009-06-30"] == True
    assert q.loc["2009-09-30"] == False


def test_split_samples_by_regime_partitions_correctly() -> None:
    """sample 의 date 기준으로 expansion / recession 분리."""
    samples = [
        HistoricalSample(date="2007-12-31", factor_z={}, bucket_returns_next={}),
        HistoricalSample(date="2008-12-31", factor_z={}, bucket_returns_next={}),
        HistoricalSample(date="2009-12-31", factor_z={}, bucket_returns_next={}),
        HistoricalSample(date="2010-12-31", factor_z={}, bucket_returns_next={}),
    ]
    recession = pd.Series(
        [False, True, True, False],
        index=pd.to_datetime(["2007-12-31", "2008-12-31",
                              "2009-12-31", "2010-12-31"]),
    )
    exp, rec = split_samples_by_regime(samples, recession)
    assert len(exp) == 2
    assert len(rec) == 2
    assert exp[0].date == "2007-12-31"
    assert rec[0].date == "2008-12-31"


def test_split_samples_unknown_date_defaults_to_expansion() -> None:
    """Recession Series 에 없는 sample date → expansion (보수적 default)."""
    samples = [
        HistoricalSample(date="1991-03-31", factor_z={}, bucket_returns_next={}),
    ]
    recession = pd.Series([], dtype=bool)
    exp, rec = split_samples_by_regime(samples, recession)
    assert len(exp) == 1
    assert len(rec) == 0


def test_nber_recession_handles_partial_quarter() -> None:
    """Quarter 의 1개월만 USREC=1 → recession=True (정책)."""
    monthly = pd.Series(
        [0, 0, 1],
        index=pd.date_range("2020-01-01", periods=3, freq="MS"),
    )
    q = nber_recession_quarterly_from_series(monthly)
    assert q.loc["2020-03-31"] == True
