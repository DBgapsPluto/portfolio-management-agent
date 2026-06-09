from datetime import date
import pandas as pd
from tradingagents.skills.technical.semi_momentum import compute_semi_momentum


def _d(values, start="2025-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_semi_momentum_basic():
    sox = _d([100.0] * 64 + [110.0])   # +10% over 63d
    smh = _d([100.0] * 64 + [105.0])   # +5%
    spy = _d([100.0] * 64 + [102.0])   # +2%
    snap = compute_semi_momentum(sox, smh, spy, as_of=date(2026, 5, 10))
    assert abs(snap.sox_ret_3m_pct - 10.0) < 0.5
    assert abs(snap.smh_vs_spy_rel_3m - 3.0) < 0.5   # 5 - 2
    assert abs(snap.sox_minus_smh_div_3m - 5.0) < 0.5  # 10 - 5


def test_semi_momentum_empty_sentinel():
    snap = compute_semi_momentum(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                 pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
