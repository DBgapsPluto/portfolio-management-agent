"""market_risk Tier-3 (KR yield curve + corp spread + margin debt + market tier) 테스트."""
from datetime import date

import pandas as pd

from tradingagents.skills.risk.kr_corp_spread import compute_kr_corp_spread
from tradingagents.skills.risk.kr_margin_debt import compute_kr_margin_debt
from tradingagents.skills.risk.kr_market_tier import compute_kr_market_tier
from tradingagents.skills.risk.kr_yield_curve import compute_kr_yield_curve


def _daily(values, start="2025-05-10"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


# ============ KR Yield Curve ============

def test_kr_yc_normal():
    y3 = _daily([3.0])
    y10 = _daily([3.7])  # +70bps
    snap = compute_kr_yield_curve(y3, y10, as_of=date(2026, 5, 10))
    assert snap.regime == "normal"
    assert snap.inverted is False
    assert abs(snap.spread_10y_3y_bps - 70.0) < 1e-6


def test_kr_yc_inverted():
    y3 = _daily([3.5])
    y10 = _daily([3.3])  # -20bps
    snap = compute_kr_yield_curve(y3, y10, as_of=date(2026, 5, 10))
    assert snap.regime == "inverted"
    assert snap.inverted is True


def test_kr_yc_flat():
    y3 = _daily([3.0])
    y10 = _daily([3.2])  # +20bps
    snap = compute_kr_yield_curve(y3, y10, as_of=date(2026, 5, 10))
    assert snap.regime == "flat"


def test_kr_yc_empty_sentinel():
    snap = compute_kr_yield_curve(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                   as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99


# ============ KR Corp Spread ============

def test_kr_corp_spread_calm():
    corp_vals = [3.5] * 100
    treas_vals = [3.0] * 100
    snap = compute_kr_corp_spread(_daily(corp_vals), _daily(treas_vals),
                                   as_of=date(2026, 5, 10))
    assert snap.regime == "calm"
    assert snap.spread_bps == 50.0  # (3.5-3.0)×100


def test_kr_corp_spread_stress():
    # 마지막에 spread 급등 → percentile > 0.85
    corp = _daily([3.5] * 99 + [4.5])
    treas = _daily([3.0] * 100)
    snap = compute_kr_corp_spread(corp, treas, as_of=date(2026, 5, 10))
    assert snap.regime == "stress"


def test_kr_corp_spread_empty_sentinel():
    snap = compute_kr_corp_spread(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                   as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99


# ============ KR Margin Debt ============

def test_kr_margin_normal():
    # 일정 수준 유지 → percentile ~0.5, change ~0
    s = _daily([1_000_000_000_000] * 252)
    snap = compute_kr_margin_debt(s, as_of=date(2026, 5, 10))
    assert snap.signal == "normal"
    assert abs(snap.change_20d_pct) < 1.0


def test_kr_margin_euphoria():
    # 1년 동안 낮게 유지하다가 마지막 20일 급증 (+15%) → percentile 1.0, change > +10%
    base = [1_000_000_000_000] * 231
    surge = [1.05e12, 1.08e12, 1.1e12, 1.12e12, 1.14e12, 1.15e12, 1.16e12, 1.17e12,
             1.18e12, 1.19e12, 1.2e12, 1.21e12, 1.22e12, 1.23e12, 1.24e12, 1.25e12,
             1.26e12, 1.27e12, 1.28e12, 1.30e12, 1.32e12]  # 21 elements
    s = _daily(base + surge)
    snap = compute_kr_margin_debt(s, as_of=date(2026, 5, 10))
    assert snap.signal == "euphoria"


def test_kr_margin_deleveraging():
    # 20일 동안 급락 (-20%)
    base = [1.5e12] * 231
    drop = [1.45e12, 1.40e12, 1.35e12, 1.30e12, 1.25e12, 1.20e12, 1.18e12, 1.15e12,
            1.13e12, 1.10e12, 1.08e12, 1.06e12, 1.05e12, 1.04e12, 1.03e12, 1.02e12,
            1.01e12, 1.00e12, 0.99e12, 0.98e12, 0.97e12]
    s = _daily(base + drop)
    snap = compute_kr_margin_debt(s, as_of=date(2026, 5, 10))
    # change_20d = (0.97e12 / 1.45e12 - 1) × 100 ≈ -33% < -15
    assert snap.signal == "deleveraging"


def test_kr_margin_empty_sentinel():
    snap = compute_kr_margin_debt(pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99


# ============ KR Market Tier ============

def test_kr_tier_small_cap_risk_on():
    # KOSPI +2%, KOSDAQ +6% → relative = +4 (>+3 → risk_on)
    kospi = _daily([2900.0] * 21)
    kospi.iloc[-1] = 2958.0  # +2%
    kosdaq = _daily([850.0] * 21)
    kosdaq.iloc[-1] = 901.0  # +6%
    snap = compute_kr_market_tier(kospi, kosdaq, as_of=date(2026, 5, 10))
    assert snap.signal == "small_cap_risk_on"
    assert snap.relative_perf_pct > 3.0


def test_kr_tier_large_cap_risk_off():
    # KOSPI flat, KOSDAQ -5% → relative = -5 (<-3 → risk_off)
    kospi = _daily([2900.0] * 21)
    kosdaq = _daily([850.0] * 21)
    kosdaq.iloc[-1] = 807.5  # -5%
    snap = compute_kr_market_tier(kospi, kosdaq, as_of=date(2026, 5, 10))
    assert snap.signal == "large_cap_risk_off"


def test_kr_tier_neutral():
    kospi = _daily([2900.0] * 21)
    kosdaq = _daily([850.0] * 21)
    # 둘 다 변화 없음 → neutral
    snap = compute_kr_market_tier(kospi, kosdaq, as_of=date(2026, 5, 10))
    assert snap.signal == "neutral"


def test_kr_tier_empty_sentinel():
    snap = compute_kr_market_tier(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                   as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99


def test_kr_yc_long_end_terms():
    y3 = _daily([3.0] * 260)
    y10 = _daily([3.7] * 260)
    y5 = _daily([3.3] * 260)
    y30 = _daily([4.0] * 260)
    snap = compute_kr_yield_curve(y3, y10, as_of=date(2026, 5, 10),
                                  treasury_5y=y5, treasury_30y=y30)
    assert abs(snap.treasury_5y - 3.3) < 1e-6
    assert abs(snap.treasury_30y - 4.0) < 1e-6
    assert abs(snap.spread_30y_5y_bps - 70.0) < 1e-6  # (4.0-3.3)*100


def test_kr_yc_long_end_optional():
    # 후방호환: 5y/30y 미제공 시 0.0
    snap = compute_kr_yield_curve(_daily([3.0]), _daily([3.7]), as_of=date(2026, 5, 10))
    assert snap.treasury_5y == 0.0
    assert snap.treasury_30y == 0.0
    assert snap.spread_30y_5y_bps == 0.0


def test_kr_yc_long_end_zero_value_not_missing():
    # 입력이 제공되면 값이 0.0이어도 spread 계산 (값 기반 판단 버그 방어)
    y5 = _daily([0.0] * 260)
    y30 = _daily([4.0] * 260)
    snap = compute_kr_yield_curve(_daily([3.0] * 260), _daily([3.7] * 260),
                                  as_of=date(2026, 5, 10), treasury_5y=y5, treasury_30y=y30)
    assert abs(snap.spread_30y_5y_bps - 400.0) < 1e-6  # (4.0-0.0)*100, NOT 0


# ============ KR Corp Spread BBB- Quality ============

def test_kr_corp_bbb_quality_spread():
    corp_aa = _daily([3.5] * 100)
    treas = _daily([3.0] * 100)
    corp_bbb = _daily([10.3] * 100)  # BBB- 등급, 훨씬 높음
    snap = compute_kr_corp_spread(corp_aa, treas, as_of=date(2026, 5, 10),
                                  corp_bbb_3y=corp_bbb)
    assert abs(snap.corp_bbb_yield_3y - 10.3) < 1e-6
    assert abs(snap.bbb_aa_quality_spread_bps - 680.0) < 1e-6  # (10.3-3.5)*100


def test_kr_corp_bbb_optional():
    snap = compute_kr_corp_spread(_daily([3.5] * 100), _daily([3.0] * 100),
                                  as_of=date(2026, 5, 10))
    assert snap.corp_bbb_yield_3y == 0.0
    assert snap.bbb_aa_quality_spread_bps == 0.0
