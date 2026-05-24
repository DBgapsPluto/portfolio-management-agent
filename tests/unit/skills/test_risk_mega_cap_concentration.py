from datetime import date

import numpy as np
import pandas as pd

from tradingagents.skills.risk.mega_cap_concentration import (
    compute_mega_cap_concentration,
)


def _series(values: list[float], start: str = "2025-05-12") -> pd.Series:
    idx = pd.date_range(start=start, periods=len(values), freq="B")
    return pd.Series(values, index=idx)


def test_returns_none_on_empty():
    assert compute_mega_cap_concentration(None, None, date(2026, 5, 10)) is None
    assert (
        compute_mega_cap_concentration(_series([]), _series([]), date(2026, 5, 10))
        is None
    )


def test_returns_none_on_short_history():
    # 29 obs < 30 threshold
    rsp = _series([100.0] * 29)
    spy = _series([100.0] * 29)
    assert compute_mega_cap_concentration(rsp, spy, date(2026, 5, 10)) is None


def test_mega_cap_heavy_low_percentile():
    # SPY 가 RSP 보다 강하게 상승 → ratio 하락 → 현재 ratio 가 1y 분포 하위.
    n = 260
    spy = np.linspace(100.0, 150.0, n)            # cap-weight 50% rally
    rsp = np.linspace(100.0, 110.0, n)            # equal-weight 10%
    pct = compute_mega_cap_concentration(_series(rsp.tolist()), _series(spy.tolist()), date(2026, 5, 10))
    assert pct is not None
    assert pct < 0.2   # mega-cap heavy


def test_broad_rally_high_percentile():
    # RSP 가 SPY 보다 강함 → ratio 상승 → 현재가 1y 상위.
    n = 260
    spy = np.linspace(100.0, 110.0, n)
    rsp = np.linspace(100.0, 130.0, n)
    pct = compute_mega_cap_concentration(_series(rsp.tolist()), _series(spy.tolist()), date(2026, 5, 10))
    assert pct is not None
    assert pct > 0.8   # broad / equal-weight 우위
