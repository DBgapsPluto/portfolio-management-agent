from datetime import date
import pandas as pd
from tradingagents.skills.macro.chip_cycle import compute_chip_cycle


def _m(values, start="2024-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


def test_chip_cycle_yoy():
    vals = [100.0] * 12 + [110.0]   # 13 months, +10% YoY
    snap = compute_chip_cycle(_m(vals), as_of=date(2026, 5, 10))
    assert abs(snap.chip_ppi_yoy_pct - 10.0) < 1e-6
    assert snap.chip_ppi == 110.0


def test_chip_cycle_empty_sentinel():
    snap = compute_chip_cycle(pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
