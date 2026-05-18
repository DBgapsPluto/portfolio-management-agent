"""Tier-2 macro skill 확장 (NFCI + 기대인플레 + Fed path) 단위 테스트."""
from datetime import date

import pandas as pd

from tradingagents.skills.macro.fed_path import compute_fed_path
from tradingagents.skills.macro.financial_conditions import compute_financial_conditions
from tradingagents.skills.macro.inflation_expectations import compute_inflation_expectations


def _weekly(values, start="2026-03-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="W"))


def _daily(values, start="2026-05-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


# ============ NFCI / Financial Conditions ============

def test_nfci_easy_regime():
    nfci = _weekly([-0.8, -0.7, -0.75, -0.72, -0.7])
    anfci = _weekly([-0.3, -0.25, -0.2, -0.18, -0.15])
    snap = compute_financial_conditions(nfci, anfci, as_of=date(2026, 5, 10))
    assert snap.regime == "easy"
    assert snap.nfci == -0.7
    assert snap.tightening is False


def test_nfci_neutral_regime():
    nfci = _weekly([0.1, 0.15, 0.2, 0.18, 0.15])
    anfci = _weekly([0.0, 0.05, 0.05, 0.05, 0.05])
    snap = compute_financial_conditions(nfci, anfci, as_of=date(2026, 5, 10))
    assert snap.regime == "neutral"


def test_nfci_tight_regime():
    nfci = _weekly([0.6, 0.7, 0.75, 0.8, 0.85])
    anfci = _weekly([0.3, 0.35, 0.4, 0.42, 0.45])
    snap = compute_financial_conditions(nfci, anfci, as_of=date(2026, 5, 10))
    assert snap.regime == "tight"
    # 0.85 - 0.6 = 0.25 > 0.2 → tightening
    assert snap.tightening is True


def test_nfci_crisis_regime():
    nfci = _weekly([1.0, 1.1, 1.2, 1.3, 1.5])
    anfci = _weekly([0.5, 0.55, 0.6, 0.65, 0.7])
    snap = compute_financial_conditions(nfci, anfci, as_of=date(2026, 5, 10))
    assert snap.regime == "crisis"


def test_nfci_no_tightening_when_easing():
    # 긴축에서 완화로 전환
    nfci = _weekly([0.8, 0.7, 0.5, 0.3, 0.2])
    anfci = _weekly([0.3, 0.25, 0.15, 0.1, 0.05])
    snap = compute_financial_conditions(nfci, anfci, as_of=date(2026, 5, 10))
    assert snap.tightening is False


# ============ Inflation Expectations ============

def test_inflation_expectations_anchored():
    breakeven = _daily([2.1, 2.2, 2.3])
    michigan = _daily([2.8, 3.0, 3.1])
    snap = compute_inflation_expectations(breakeven, michigan, as_of=date(2026, 5, 10))
    assert snap.anchored is True
    assert snap.unanchored_direction == "none"


def test_inflation_expectations_upside_unanchored_via_breakeven():
    breakeven = _daily([3.0, 3.2, 3.5])
    michigan = _daily([3.0, 3.2, 3.5])
    snap = compute_inflation_expectations(breakeven, michigan, as_of=date(2026, 5, 10))
    assert snap.anchored is False
    assert snap.unanchored_direction == "upside"


def test_inflation_expectations_upside_via_michigan():
    breakeven = _daily([2.5, 2.5, 2.5])  # anchored
    michigan = _daily([4.0, 4.2, 4.5])   # unanchored upside
    snap = compute_inflation_expectations(breakeven, michigan, as_of=date(2026, 5, 10))
    assert snap.anchored is False
    assert snap.unanchored_direction == "upside"


def test_inflation_expectations_downside():
    breakeven = _daily([1.5, 1.3, 1.2])
    michigan = _daily([2.5, 2.3, 2.2])
    snap = compute_inflation_expectations(breakeven, michigan, as_of=date(2026, 5, 10))
    assert snap.anchored is False
    assert snap.unanchored_direction == "downside"


# ============ Fed Path ============

def test_fed_path_hike_expected():
    # DGS2 = 5.2%, DFF = 4.5% → +70 bps → hike
    dgs2 = _daily([5.1, 5.15, 5.2])
    dff = _daily([4.5, 4.5, 4.5])
    snap = compute_fed_path(dff, dgs2, as_of=date(2026, 5, 10))
    assert snap.market_view == "hike"
    assert snap.path_bps > 50


def test_fed_path_cut_expected():
    # DGS2 = 4.0%, DFF = 5.25% → -125 bps → cut
    dgs2 = _daily([4.0, 4.0, 4.0])
    dff = _daily([5.25, 5.25, 5.25])
    snap = compute_fed_path(dff, dgs2, as_of=date(2026, 5, 10))
    assert snap.market_view == "cut"
    assert snap.path_bps < -50


def test_fed_path_hold_within_band():
    # |gap| < 50 bps → hold
    dgs2 = _daily([4.55, 4.55, 4.55])
    dff = _daily([4.5, 4.5, 4.5])
    snap = compute_fed_path(dff, dgs2, as_of=date(2026, 5, 10))
    assert snap.market_view == "hold"
    assert abs(snap.path_bps) < 50
