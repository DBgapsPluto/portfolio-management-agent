from datetime import date
import pandas as pd
from tradingagents.skills.macro.fx import compute_fx_overlay


def _d(values, start="2025-05-10"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_fx_jpy_krw_cross():
    usd_krw = _d([1555.96] * 30)
    dxy = _d([100.0] * 30)
    usd_jpy = _d([160.26] * 30)
    snap = compute_fx_overlay(usd_krw, dxy, as_of=date(2026, 6, 9), usd_jpy=usd_jpy)
    assert abs(snap.jpy_krw - (1555.96 / 160.26)) < 1e-4   # ≈ 9.71
    assert snap.jpy_krw_change_1m_pct == 0.0  # 평탄


def test_fx_jpy_optional():
    snap = compute_fx_overlay(_d([1300.0] * 30), _d([100.0] * 30), as_of=date(2026, 6, 9))
    assert snap.jpy_krw == 0.0
