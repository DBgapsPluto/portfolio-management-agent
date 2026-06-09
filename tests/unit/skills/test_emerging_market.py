from datetime import date
import pandas as pd
from tradingagents.skills.macro.emerging_market import compute_emerging_market


def _d(values, start="2025-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_em_basic():
    eem = _d([100.0] * 64 + [108.0])   # +8% 3m
    emb = _d([100.0] * 64 + [102.0])
    dxy = _d([100.0] * 64 + [98.0])    # DXY -2%
    snap = compute_emerging_market(eem, emb, dxy, as_of=date(2026, 5, 10))
    assert abs(snap.em_equity_ret_3m_pct - 8.0) < 0.5
    assert snap.regime == "risk_on"


def test_em_empty_sentinel():
    snap = compute_emerging_market(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                   pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
