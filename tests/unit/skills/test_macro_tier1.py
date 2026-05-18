"""Tier-1 macro skill 확장 (KR exports/CLI/BSI + US CFNAI + GDPNow) 단위 테스트."""
from datetime import date

import pandas as pd

from tradingagents.skills.macro.gdp_nowcast import compute_gdp_nowcast
from tradingagents.skills.macro.kr_business_survey import compute_kr_business_survey
from tradingagents.skills.macro.kr_exports import compute_kr_export_trend
from tradingagents.skills.macro.kr_leading import compute_kr_leading_index
from tradingagents.skills.macro.us_leading import compute_us_leading_index


# ============ KR exports ============

def _monthly(values, start="2025-05-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


def test_kr_export_yoy_positive():
    # 100→110 over 12 months = ~10% YoY
    values = [100.0 * (1.10) ** (i / 12) for i in range(13)]
    snap = compute_kr_export_trend(_monthly(values), as_of=date(2026, 5, 10))
    assert 9.0 < snap.yoy_pct < 11.0


def test_kr_export_accelerating_true():
    # 마지막 3개월에서 가속
    values = [100.0] * 9 + [102.0, 105.0, 109.0, 114.0]
    snap = compute_kr_export_trend(_monthly(values), as_of=date(2026, 5, 10))
    assert snap.accelerating is True
    assert snap.momentum_3mo_pct > snap.momentum_6mo_pct


def test_kr_export_zero_base_safe():
    # 0으로 나누는 경계 케이스 (실제 데이터에선 거의 없지만 방어)
    values = [0.0] * 12 + [100.0]
    snap = compute_kr_export_trend(_monthly(values), as_of=date(2026, 5, 10))
    assert snap.yoy_pct == 0.0


# ============ KR leading index ============

def test_kr_cli_expansion_phase():
    # 100 이상 + 상승 추세 → expansion
    values = [99.0, 99.5, 100.0, 100.5, 101.0, 101.5, 102.0]
    snap = compute_kr_leading_index(_monthly(values), as_of=date(2026, 5, 10))
    assert snap.cli_value == 102.0
    assert snap.phase == "expansion"
    assert snap.change_3mo > 0


def test_kr_cli_contraction_phase():
    # 100 미만 + 하락 → contraction
    values = [101.0, 100.5, 100.0, 99.5, 99.0, 98.5, 98.0]
    snap = compute_kr_leading_index(_monthly(values), as_of=date(2026, 5, 10))
    assert snap.phase == "contraction"


def test_kr_cli_trough_phase():
    # 100 미만 + 반등 → trough
    values = [99.0, 98.0, 97.0, 96.0, 96.5, 97.0, 98.0]
    snap = compute_kr_leading_index(_monthly(values), as_of=date(2026, 5, 10))
    assert snap.phase == "trough"


# ============ KR business survey (BSI) ============

def test_kr_bsi_normal():
    values = [95.0, 97.0, 98.0, 99.0]
    snap = compute_kr_business_survey(_monthly(values), as_of=date(2026, 5, 10))
    assert snap.mfg_bsi == 99.0
    assert snap.contraction_signal is False
    assert snap.change_3mo == 4.0


def test_kr_bsi_contraction():
    # BSI 80 미만 = 명확한 위축
    values = [85.0, 80.0, 78.0, 75.0]
    snap = compute_kr_business_survey(_monthly(values), as_of=date(2026, 5, 10))
    assert snap.contraction_signal is True


# ============ US CFNAI ============

def test_cfnai_normal_expansion():
    cfnai = _monthly([0.1, 0.2, 0.15, 0.05])
    ma3 = _monthly([0.05, 0.1, 0.15, 0.13])
    snap = compute_us_leading_index(cfnai, ma3, as_of=date(2026, 5, 10))
    assert snap.recession_signal is False
    assert snap.cfnai_ma3 == 0.13


def test_cfnai_recession_threshold():
    # CFNAIMA3 < -0.7 = recession entry
    cfnai = _monthly([-0.5, -0.8, -1.0, -1.2])
    ma3 = _monthly([-0.3, -0.5, -0.77, -1.0])
    snap = compute_us_leading_index(cfnai, ma3, as_of=date(2026, 5, 10))
    assert snap.recession_signal is True
    assert snap.cfnai_ma3 < -0.7


def test_cfnai_borderline_not_recession():
    # -0.7 정확히는 recession 아님 (< 비교)
    cfnai = _monthly([-0.5, -0.6, -0.7])
    ma3 = _monthly([-0.5, -0.6, -0.7])
    snap = compute_us_leading_index(cfnai, ma3, as_of=date(2026, 5, 10))
    assert snap.recession_signal is False


# ============ GDP nowcast ============

def test_gdp_nowcast_change():
    s = pd.Series([2.5, 2.7, 3.0, 2.8])
    snap = compute_gdp_nowcast(s, as_of=date(2026, 5, 10))
    assert snap.nowcast_pct == 2.8
    assert abs(snap.change_from_prior - (-0.2)) < 1e-9


def test_gdp_nowcast_single_point():
    s = pd.Series([2.5])
    snap = compute_gdp_nowcast(s, as_of=date(2026, 5, 10))
    assert snap.nowcast_pct == 2.5
    assert snap.change_from_prior == 0.0
