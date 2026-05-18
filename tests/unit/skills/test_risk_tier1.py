"""market_risk Tier-1 확장 (VIX term + SKEW + VXN + VKOSPI 4w + breadth real) 단위 테스트."""
from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.skills.risk.skew_index import compute_skew_index
from tradingagents.skills.risk.vix_term_structure import compute_vix_term_structure
from tradingagents.skills.risk.volatility import fetch_volatility_index
from tradingagents.skills.risk.vxn import compute_vxn


def _daily(values, start="2025-05-10"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


# ============ VIX term structure ============

def test_vix_term_contango():
    vix_front = _daily([18.0])
    vix_3m = _daily([21.0])  # 21/18 = 1.167 → contango
    snap = compute_vix_term_structure(vix_front, vix_3m, as_of=date(2026, 5, 10))
    assert snap.regime == "contango"
    assert snap.ratio > 1.05


def test_vix_term_backwardation():
    vix_front = _daily([35.0])  # 패닉 spike
    vix_3m = _daily([28.0])  # 28/35 = 0.8 → backwardation
    snap = compute_vix_term_structure(vix_front, vix_3m, as_of=date(2026, 5, 10))
    assert snap.regime == "backwardation"
    assert snap.ratio < 0.95


def test_vix_term_flat():
    vix_front = _daily([20.0])
    vix_3m = _daily([20.5])  # ratio ~1.025 → flat
    snap = compute_vix_term_structure(vix_front, vix_3m, as_of=date(2026, 5, 10))
    assert snap.regime == "flat"


def test_vix_term_zero_safe():
    # front=0 → division 방지, ratio=1.0 fallback
    vix_front = _daily([0.0])
    vix_3m = _daily([20.0])
    snap = compute_vix_term_structure(vix_front, vix_3m, as_of=date(2026, 5, 10))
    assert snap.ratio == 1.0


# ============ SKEW ============

def test_skew_low():
    s = _daily([115.0] * 252)
    snap = compute_skew_index(s, as_of=date(2026, 5, 10))
    assert snap.tail_hedge_signal == "low"
    assert snap.skew_value == 115.0


def test_skew_normal():
    s = _daily([125.0] * 252)
    snap = compute_skew_index(s, as_of=date(2026, 5, 10))
    assert snap.tail_hedge_signal == "normal"


def test_skew_elevated():
    s = _daily([138.0] * 252)
    snap = compute_skew_index(s, as_of=date(2026, 5, 10))
    assert snap.tail_hedge_signal == "elevated"


def test_skew_extreme():
    s = _daily([150.0] * 252)
    snap = compute_skew_index(s, as_of=date(2026, 5, 10))
    assert snap.tail_hedge_signal == "extreme"


def test_skew_empty_sentinel():
    snap = compute_skew_index(pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.tail_hedge_signal == "normal"
    assert snap.staleness_days == 99


# ============ VXN ============

def test_vxn_high_spread_vs_vix():
    vxn = _daily([28.0] * 252)
    vix = _daily([20.0] * 252)
    snap = compute_vxn(vxn, vix, as_of=date(2026, 5, 10))
    assert snap.spread_vs_vix == 8.0  # 28-20
    assert snap.current_value == 28.0


def test_vxn_negative_spread():
    vxn = _daily([18.0] * 252)
    vix = _daily([22.0] * 252)
    snap = compute_vxn(vxn, vix, as_of=date(2026, 5, 10))
    assert snap.spread_vs_vix == -4.0


def test_vxn_empty_sentinel():
    snap = compute_vxn(pd.Series([], dtype=float), pd.Series([], dtype=float),
                       as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
    assert snap.spread_vs_vix == 0.0


# ============ Volatility skill 강화 (change_4w 추가) ============

def test_volatility_change_4w_positive():
    # 25일 series. iloc[-21]은 idx 4 = 16. iloc[-1] = 20. diff = +4.
    series = pd.Series([15.0] * 4 + [16.0] * 5 + [18.0] * 7 + [20.0] * 9)
    with patch(
        "tradingagents.skills.risk.volatility.fetch_vix",
        return_value=series,
    ):
        snap = fetch_volatility_index("VIX", as_of=date(2026, 5, 10))
    assert snap.change_4w == 4.0
    assert snap.current_value == 20.0


def test_volatility_change_4w_negative():
    # iloc[-21]=idx 4 = 22, iloc[-1]=18 → diff = -4
    series = pd.Series([25.0] * 4 + [22.0] * 5 + [20.0] * 7 + [18.0] * 9)
    with patch(
        "tradingagents.skills.risk.volatility.fetch_vix",
        return_value=series,
    ):
        snap = fetch_volatility_index("VIX", as_of=date(2026, 5, 10))
    assert snap.change_4w == -4.0


def test_volatility_short_series_change_4w_zero():
    series = pd.Series([15.0, 16.0, 17.0])  # < 21
    with patch(
        "tradingagents.skills.risk.volatility.fetch_vix",
        return_value=series,
    ):
        snap = fetch_volatility_index("VIX", as_of=date(2026, 5, 10))
    assert snap.change_4w == 0.0
