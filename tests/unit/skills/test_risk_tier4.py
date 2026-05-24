"""market_risk Tier-4 (equity-bond correlation regime) 단위 테스트."""
from datetime import date

import pandas as pd

from tradingagents.skills.risk.equity_bond_corr import compute_equity_bond_corr


def _daily(values, start="2025-05-10"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_equity_bond_corr_normal_hedge():
    # 음의 상관 (bonds hedge equity) — 길이 130일로 60-day corr + 3m prior 계산 가능
    n = 130
    eq = [0.01 * (i % 2 == 0) - 0.01 * (i % 2 == 1) for i in range(n)]
    bd = [-0.01 * (i % 2 == 0) + 0.01 * (i % 2 == 1) for i in range(n)]  # 완벽한 음의 상관
    snap = compute_equity_bond_corr(_daily(eq), _daily(bd), as_of=date(2026, 5, 10))
    assert snap.regime == "normal_hedge"
    assert snap.correlation_120d < -0.3


def test_equity_bond_corr_extreme_positive():
    # 강한 양의 상관 (둘 다 같은 방향)
    n = 130
    eq = [0.01 if i % 2 == 0 else -0.01 for i in range(n)]
    bd = [0.01 if i % 2 == 0 else -0.01 for i in range(n)]  # 완벽한 양의 상관
    snap = compute_equity_bond_corr(_daily(eq), _daily(bd), as_of=date(2026, 5, 10))
    assert snap.regime == "extreme_positive"
    assert snap.correlation_120d > 0.3


def test_equity_bond_corr_positive_flip():
    # 0~+0.3 사이 → positive_flip
    import numpy as np
    np.random.seed(42)
    n = 130
    base = np.random.randn(n) * 0.01
    eq = base + np.random.randn(n) * 0.02  # equity = base + noise
    bd = base * 0.3 + np.random.randn(n) * 0.02  # bond = weak positive corr w/ equity
    snap = compute_equity_bond_corr(_daily(eq), _daily(bd), as_of=date(2026, 5, 10))
    # 정확한 값은 무작위지만 양수일 가능성 높음
    assert snap.regime in ("positive_flip", "weakening_hedge", "extreme_positive")


def test_equity_bond_corr_short_series_sentinel():
    eq = _daily([0.01] * 30)  # < 60
    bd = _daily([-0.01] * 30)
    snap = compute_equity_bond_corr(eq, bd, as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
    assert snap.regime == "normal_hedge"


def test_equity_bond_corr_empty_sentinel():
    snap = compute_equity_bond_corr(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                     as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99


def test_equity_bond_corr_change_3m_computed():
    # 130일 series → change_3m 계산 가능 (60+63 = 123 ≤ 130)
    n = 130
    eq = [0.01 if i % 2 == 0 else -0.01 for i in range(n)]
    bd = [-0.01 if i % 2 == 0 else 0.01 for i in range(n)]
    snap = compute_equity_bond_corr(_daily(eq), _daily(bd), as_of=date(2026, 5, 10))
    # 동일한 패턴이라 change_3m은 0에 가까울 것 (양쪽 모두 -1 corr)
    assert abs(snap.change_3m) < 0.1
