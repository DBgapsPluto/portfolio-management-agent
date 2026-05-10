from datetime import date

import pandas as pd
import pytest

from tradingagents.skills.macro.yield_curve import compute_yield_curve


def test_normal_curve():
    s_10y = pd.Series([4.5, 4.4, 4.3], index=pd.date_range("2026-05-08", periods=3))
    s_2y = pd.Series([4.0, 4.0, 3.9], index=pd.date_range("2026-05-08", periods=3))
    s_3m = pd.Series([5.0, 5.0, 5.0], index=pd.date_range("2026-05-08", periods=3))

    snap = compute_yield_curve(s_10y, s_2y, s_3m, as_of=date(2026, 5, 10))
    assert snap.spread_10y_2y_bps == pytest.approx(40.0, abs=0.1)


def test_inverted_curve():
    s_10y = pd.Series([3.5], index=[pd.Timestamp("2026-05-10")])
    s_2y = pd.Series([4.0], index=[pd.Timestamp("2026-05-10")])
    s_3m = pd.Series([4.5], index=[pd.Timestamp("2026-05-10")])

    snap = compute_yield_curve(s_10y, s_2y, s_3m, as_of=date(2026, 5, 10))
    assert snap.spread_10y_2y_bps < 0
    assert snap.spread_10y_3m_bps < 0


def test_inverted_days_count():
    dates = pd.date_range("2025-12-01", periods=10)
    s_10y = pd.Series([4.5, 4.5, 4.5, 4.5, 4.5, 3.9, 3.9, 3.8, 4.0, 4.5], index=dates)
    s_2y = pd.Series([4.0] * 10, index=dates)
    s_3m = pd.Series([4.0] * 10, index=dates)

    snap = compute_yield_curve(s_10y, s_2y, s_3m, as_of=date(2026, 5, 10))
    assert snap.inverted_days_count == 3
