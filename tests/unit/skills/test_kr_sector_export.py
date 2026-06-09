from datetime import date
import pandas as pd
from tradingagents.skills.macro.kr_sector_export import compute_kr_sector_export


def _m(values, start="2024-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


def test_sector_export_yoy():
    series = {
        "semi": _m([100.0] * 12 + [120.0]),     # +20% YoY (leader)
        "battery": _m([100.0] * 12 + [95.0]),   # -5% (laggard)
        "display": _m([100.0] * 12 + [110.0]),
        "chem": _m([100.0] * 12 + [105.0]),
        "steel": _m([100.0] * 12 + [102.0]),
    }
    snap = compute_kr_sector_export(series, as_of=date(2026, 5, 10))
    assert abs(snap.semi_yoy_pct - 20.0) < 1e-6
    assert snap.leader_sector == "semi"
    assert snap.laggard_sector == "battery"


def test_sector_export_empty_sentinel():
    snap = compute_kr_sector_export({}, as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
