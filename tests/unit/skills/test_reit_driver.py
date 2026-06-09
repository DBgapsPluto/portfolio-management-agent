from datetime import date
import pandas as pd
from tradingagents.skills.risk.reit_driver import compute_reit_driver


def _d(values, start="2025-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_reit_driver_basic():
    vnq = _d([100.0] * 64 + [106.0])    # +6% 3m
    xlre = _d([100.0] * 64 + [104.0])
    schh = _d([100.0] * 64 + [105.0])
    mortgage = _d([7.0] * 30)
    dgs10 = _d([4.0] * 30)
    snap = compute_reit_driver(vnq, xlre, schh, mortgage, dgs10, as_of=date(2026, 5, 10))
    assert abs(snap.us_reit_ret_3m_pct - 6.0) < 0.5
    assert abs(snap.mortgage_30y - 7.0) < 1e-6
    assert abs(snap.mortgage_minus_10y_bps - 300.0) < 1e-6  # (7-4)*100


def test_reit_driver_empty_sentinel():
    e = pd.Series([], dtype=float)
    snap = compute_reit_driver(e, e, e, e, e, as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
