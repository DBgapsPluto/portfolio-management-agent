"""Tier-4 macro skill 확장 (Policy Uncertainty + Tail Risk) 단위 테스트."""
from datetime import date

import pandas as pd

from tradingagents.skills.macro.policy_uncertainty import compute_policy_uncertainty
from tradingagents.skills.macro.tail_risk import compute_tail_risk


def _monthly(values, start="2021-05-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


def _daily(values, start="2025-05-10"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


# ============ Policy Uncertainty ============

def test_epu_normal_regime():
    us = _monthly([100.0] * 59 + [120.0])
    glob = _monthly([105.0] * 60)
    snap = compute_policy_uncertainty(us, glob, as_of=date(2026, 5, 10))
    assert snap.regime == "normal"
    assert snap.us_epu == 120.0


def test_epu_elevated_regime():
    us = _monthly([100.0] * 59 + [170.0])
    glob = _monthly([130.0] * 60)
    snap = compute_policy_uncertainty(us, glob, as_of=date(2026, 5, 10))
    assert snap.regime == "elevated"


def test_epu_extreme_regime():
    us = _monthly([100.0] * 59 + [250.0])
    glob = _monthly([200.0] * 60)
    snap = compute_policy_uncertainty(us, glob, as_of=date(2026, 5, 10))
    assert snap.regime == "extreme"
    assert snap.us_epu_percentile_5y > 0.95


def test_epu_percentile_mid():
    # 50개는 50, 9개는 100, 마지막 = 80 → percentile ≈ 50/60 ≈ 0.83
    us = _monthly([50.0] * 50 + [100.0] * 9 + [80.0])
    glob = _monthly([80.0] * 60)
    snap = compute_policy_uncertainty(us, glob, as_of=date(2026, 5, 10))
    assert 0.8 < snap.us_epu_percentile_5y < 0.9


# ============ Tail Risk ============

def test_tail_risk_calm():
    vvix = _daily([85.0] * 252)
    move = _daily([90.0] * 252)
    snap = compute_tail_risk(vvix, move, as_of=date(2026, 5, 10))
    assert snap.signal == "calm"


def test_tail_risk_elevated_via_vvix():
    # VVIX 상위 80%, MOVE 정상 → elevated
    vvix = _daily([80.0] * 200 + [120.0] * 52)
    move = _daily([90.0] * 252)
    snap = compute_tail_risk(vvix, move, as_of=date(2026, 5, 10))
    assert snap.signal == "elevated"


def test_tail_risk_extreme_both_high():
    # 둘 다 100% percentile (마지막이 최댓값) → extreme
    vvix = _daily([80.0] * 251 + [150.0])
    move = _daily([90.0] * 251 + [180.0])
    snap = compute_tail_risk(vvix, move, as_of=date(2026, 5, 10))
    assert snap.signal == "extreme"
    assert snap.vvix_percentile_1y > 0.9
    assert snap.move_percentile_1y > 0.9


def test_tail_risk_extreme_requires_both():
    # 하나만 0.9+면 elevated, 둘 다여야 extreme
    vvix = _daily([80.0] * 251 + [150.0])  # percentile = 1.0
    move = _daily([90.0] * 200 + [100.0] * 52)  # percentile = ~0.20
    snap = compute_tail_risk(vvix, move, as_of=date(2026, 5, 10))
    assert snap.signal == "elevated"  # extreme 아님 — MOVE 정상
