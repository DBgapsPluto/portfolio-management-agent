"""Tier-3 macro skill 확장 (FX + Copper/Gold + China CLI + 외국인 flow) 단위 테스트."""
from datetime import date

import pandas as pd

from tradingagents.skills.macro.china_leading import compute_china_leading
from tradingagents.skills.macro.foreign_flow import compute_foreign_flow
from tradingagents.skills.macro.fx import compute_fx_overlay
from tradingagents.skills.macro.risk_appetite import compute_risk_appetite


def _daily(values, start="2026-04-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def _monthly(values, start="2025-04-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


# ============ FX overlay ============

def test_fx_krw_weak_regime():
    # 1300 → 1340 (≈+3% over 22 days)
    krw_vals = [1300.0] + [1300 + i * 2 for i in range(21)]
    krw = _daily(krw_vals)
    dxy = _daily([100.0] * 22)  # DXY 변화 없음
    snap = compute_fx_overlay(krw, dxy, as_of=date(2026, 5, 10))
    assert snap.regime == "krw_weak"
    assert snap.krw_change_1m_pct > 2.0


def test_fx_usd_risk_off_regime():
    # KRW 약세 + DXY 강세 동시 → usd_risk_off
    krw = _daily([1300.0] + [1300 + i * 2 for i in range(21)])
    dxy = _daily([100.0] + [100 + i * 0.1 for i in range(21)])
    snap = compute_fx_overlay(krw, dxy, as_of=date(2026, 5, 10))
    assert snap.regime == "usd_risk_off"


def test_fx_krw_strong_regime():
    # 1300 → 1260 (-3%)
    krw = _daily([1300.0] + [1300 - i * 2 for i in range(21)])
    dxy = _daily([100.0] * 22)
    snap = compute_fx_overlay(krw, dxy, as_of=date(2026, 5, 10))
    assert snap.regime == "krw_strong"


def test_fx_neutral_small_change():
    # 1300 → 1305 (+0.4%) → neutral
    krw = _daily([1300.0] + [1300 + i * 0.25 for i in range(21)])
    dxy = _daily([100.0] * 22)
    snap = compute_fx_overlay(krw, dxy, as_of=date(2026, 5, 10))
    assert snap.regime == "neutral"


# ============ Risk Appetite (Copper/Gold) ============

def test_copper_gold_risk_on():
    # 마지막 ratio가 1년 상위 70%+ 위치
    cu_vals = [4.0] * 250 + [4.5, 4.8]
    au_vals = [2000.0] * 252
    cu = _daily(cu_vals, start="2025-05-10")
    au = _daily(au_vals, start="2025-05-10")
    snap = compute_risk_appetite(cu, au, as_of=date(2026, 5, 10))
    assert snap.signal == "risk_on"
    assert snap.ratio_percentile_1y > 0.7


def test_copper_gold_risk_off():
    # 마지막 ratio가 1년 하위 30%
    cu_vals = [5.0] * 250 + [3.5, 3.0]
    au_vals = [2000.0] * 252
    cu = _daily(cu_vals, start="2025-05-10")
    au = _daily(au_vals, start="2025-05-10")
    snap = compute_risk_appetite(cu, au, as_of=date(2026, 5, 10))
    assert snap.signal == "risk_off"
    assert snap.ratio_percentile_1y < 0.3


def test_copper_gold_empty_returns_sentinel():
    cu = pd.Series([], dtype=float)
    au = pd.Series([], dtype=float)
    snap = compute_risk_appetite(cu, au, as_of=date(2026, 5, 10))
    assert snap.signal == "neutral"
    assert snap.staleness_days == 99


# ============ China CLI ============

def test_china_cli_expansion():
    # 100 이상 + 상승
    vals = [99.5, 100.0, 100.5, 101.0, 101.5]
    snap = compute_china_leading(_monthly(vals), as_of=date(2026, 5, 10))
    assert snap.phase == "expansion"


def test_china_cli_contraction():
    vals = [101.0, 100.5, 99.5, 98.5, 97.5]
    snap = compute_china_leading(_monthly(vals), as_of=date(2026, 5, 10))
    assert snap.phase == "contraction"


def test_china_cli_trough():
    vals = [99.0, 98.0, 97.5, 98.0, 99.0]
    snap = compute_china_leading(_monthly(vals), as_of=date(2026, 5, 10))
    assert snap.phase == "trough"


# ============ Foreign Flow ============

def test_foreign_flow_net_buying():
    # 20일 누적 +1.5조
    daily = [75_000_000_000] * 20  # 750억 × 20일 = 1.5조
    snap = compute_foreign_flow(pd.Series(daily), as_of=date(2026, 5, 10))
    assert snap.signal == "net_buying"
    assert snap.net_20d_krw > 1e12


def test_foreign_flow_net_selling():
    daily = [-75_000_000_000] * 20  # -1.5조
    snap = compute_foreign_flow(pd.Series(daily), as_of=date(2026, 5, 10))
    assert snap.signal == "net_selling"


def test_foreign_flow_neutral():
    daily = [10_000_000_000] * 20  # 100억 × 20 = 2000억 (1조 미만)
    snap = compute_foreign_flow(pd.Series(daily), as_of=date(2026, 5, 10))
    assert snap.signal == "neutral"


def test_foreign_flow_empty_returns_sentinel():
    snap = compute_foreign_flow(pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.signal == "neutral"
    assert snap.staleness_days == 99
