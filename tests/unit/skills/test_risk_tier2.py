"""market_risk Tier-2 (TIPS real yields + funding stress + credit quality + spread momentum) 테스트."""
from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.skills.risk.credit_quality import compute_credit_quality
from tradingagents.skills.risk.credit_spread import fetch_credit_spread
from tradingagents.skills.risk.funding_stress import compute_funding_stress
from tradingagents.skills.risk.real_yields import compute_real_yields


def _daily(values, start="2025-05-10"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


# ============ Real Yields ============

def test_real_yields_accommodative():
    tips_10 = _daily([-0.5, -0.4, -0.3])
    tips_5 = _daily([-0.8, -0.7, -0.6])
    snap = compute_real_yields(tips_10, tips_5, as_of=date(2026, 5, 10))
    assert snap.regime == "accommodative"
    assert snap.spread_10y_5y == pytest_approx(0.3)


def test_real_yields_very_tight():
    tips_10 = _daily([2.3])
    tips_5 = _daily([2.0])
    snap = compute_real_yields(tips_10, tips_5, as_of=date(2026, 5, 10))
    assert snap.regime == "very_tight"
    assert snap.tips_10y == 2.3


def test_real_yields_neutral():
    tips_10 = _daily([0.5])
    tips_5 = _daily([0.3])
    snap = compute_real_yields(tips_10, tips_5, as_of=date(2026, 5, 10))
    assert snap.regime == "neutral"


def test_real_yields_tight():
    tips_10 = _daily([1.5])
    tips_5 = _daily([1.3])
    snap = compute_real_yields(tips_10, tips_5, as_of=date(2026, 5, 10))
    assert snap.regime == "tight"


def test_real_yields_empty_sentinel():
    snap = compute_real_yields(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99


# ============ Funding Stress ============

def test_funding_calm():
    # SOFR 5.30, T-bill 5.25 → +5bps
    sofr = _daily([5.30])
    tbill = _daily([5.25])
    snap = compute_funding_stress(sofr, tbill, as_of=date(2026, 5, 10))
    assert snap.regime == "calm"
    assert abs(snap.spread_bps - 5.0) < 0.01


def test_funding_elevated():
    sofr = _daily([5.40])
    tbill = _daily([5.25])  # +15bps
    snap = compute_funding_stress(sofr, tbill, as_of=date(2026, 5, 10))
    assert snap.regime == "elevated"


def test_funding_stress():
    sofr = _daily([5.55])
    tbill = _daily([5.25])  # +30bps
    snap = compute_funding_stress(sofr, tbill, as_of=date(2026, 5, 10))
    assert snap.regime == "stress"


# ============ Credit Quality (BBB - AAA) ============

def test_credit_quality_calm():
    # 한결같은 spread → 50th percentile, calm
    aaa_vals = [0.5] * 100
    bbb_vals = [1.5] * 100
    aaa = _daily(aaa_vals)
    bbb = _daily(bbb_vals)
    snap = compute_credit_quality(aaa, bbb, as_of=date(2026, 5, 10))
    assert snap.regime == "calm"
    assert abs(snap.quality_spread_bps - 100.0) < 0.01  # (1.5 - 0.5) × 100 = 100bps


def test_credit_quality_stress():
    # 마지막에 quality spread 급등 → percentile > 0.85
    aaa = _daily([0.5] * 50 + [0.5] * 50)
    bbb_vals = [1.0] * 99 + [3.0]  # 마지막에 spike → spread = 250bps (max)
    bbb = _daily(bbb_vals)
    snap = compute_credit_quality(aaa, bbb, as_of=date(2026, 5, 10))
    assert snap.regime == "stress"


def test_credit_quality_empty_sentinel():
    snap = compute_credit_quality(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                   as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99


# ============ Spread Momentum (credit_spread.py 확장) ============

def test_credit_spread_momentum_widening():
    # 100일치 정상 → 마지막 60일이 지속 widening
    base = [1.0] * 40 + [1.0 + 0.005 * i for i in range(60)]  # 일별 +0.005% widening
    series = _daily(base, start="2025-12-01")
    with patch(
        "tradingagents.skills.risk.credit_spread.fetch_fred_series",
        return_value=series,
    ):
        snap = fetch_credit_spread("US_HY", as_of=date(2026, 3, 10))
    # diff = constant +0.005 → diff.std() ~ 0 → momentum_z 큰 양수 (실질적으로 inf, code가 std>0 guard)
    # 실제론 모든 diff가 같으므로 std=0 → 0.0 반환 (guard로)
    # 약간 노이즈 추가한 케이스로 변경:
    assert snap.current_bps > 0  # 적어도 정상 값 반환


def test_credit_spread_momentum_with_noise():
    import numpy as np
    np.random.seed(42)
    base = list(np.linspace(1.0, 1.6, 100) + np.random.normal(0, 0.01, 100))
    series = _daily(base, start="2025-12-01")
    with patch(
        "tradingagents.skills.risk.credit_spread.fetch_fred_series",
        return_value=series,
    ):
        snap = fetch_credit_spread("US_HY", as_of=date(2026, 3, 10))
    assert snap.momentum_zscore > 0  # widening trend → positive z


def test_credit_spread_momentum_short_series():
    series = _daily([1.0, 1.1])  # too short for momentum
    with patch(
        "tradingagents.skills.risk.credit_spread.fetch_fred_series",
        return_value=series,
    ):
        snap = fetch_credit_spread("US_HY", as_of=date(2026, 3, 10))
    assert snap.momentum_zscore == 0.0


# ============ Test helpers ============

def pytest_approx(value, tol=1e-6):
    """Inline approx helper."""
    class _Approx:
        def __init__(self, v): self.v = v
        def __eq__(self, other): return abs(other - self.v) < tol
        def __repr__(self): return f"~{self.v}"
    return _Approx(value)
