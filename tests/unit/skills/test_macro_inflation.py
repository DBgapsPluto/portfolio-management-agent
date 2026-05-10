from datetime import date
import pandas as pd
from tradingagents.skills.macro.inflation import compute_inflation_trend


def test_inflation_decelerating():
    cpi = pd.Series([100, 101, 102, 103, 104, 104.5, 104.8, 105.0, 105.1, 105.15, 105.18, 105.20, 105.21],
                    index=pd.date_range("2025-05-01", periods=13, freq="MS"))
    snap = compute_inflation_trend(cpi, core_cpi=cpi.copy(), as_of=date(2026, 5, 10))
    assert snap.accelerating is False
    assert snap.cpi_yoy > 0


def test_inflation_accelerating():
    months = pd.date_range("2025-05-01", periods=13, freq="MS")
    vals = [100, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7, 100.8, 102, 104, 106, 108]
    cpi = pd.Series(vals, index=months)
    snap = compute_inflation_trend(cpi, core_cpi=cpi.copy(), as_of=date(2026, 5, 10))
    assert snap.accelerating is True
