"""compute_skew_change_z tests (C7.5 — F7 skew_change placeholder 해소).

D7 pattern (기존 schema 확장): scalar return — analyst 가 SkewSnapshot.model_copy
로 change_1m_z field 에 채움.
D8 pattern: insufficient series / empty / exception → None (graceful skip).
D9 pattern: no retry, no cache in skill.

Hand-coded long-run sd = 5.0; lookback = 21 trading days (1 month).
"""
from datetime import date

import pandas as pd
import pytest

from tradingagents.skills.risk.skew_metrics import compute_skew_change_z


def test_skew_change_z_basic_positive():
    """Latest +10 above 21d ago, sd=5 → z=+2."""
    # 22 obs: iloc[-21] = first sample (100), iloc[-1] = last sample (110)
    series = pd.Series([100.0] * 21 + [110.0])
    z = compute_skew_change_z(series, as_of=date.today())
    assert z == pytest.approx(2.0)


def test_skew_change_z_negative():
    """Latest -10 below 21d ago → z=-2."""
    series = pd.Series([120.0] * 21 + [110.0])
    z = compute_skew_change_z(series, as_of=date.today())
    assert z == pytest.approx(-2.0)


def test_skew_change_z_no_change():
    """Flat series → z=0."""
    series = pd.Series([120.0] * 22)
    z = compute_skew_change_z(series, as_of=date.today())
    assert z == pytest.approx(0.0)


def test_skew_change_z_short_series_returns_none():
    """<21 obs → None (D8 graceful)."""
    series = pd.Series([120.0] * 10)
    z = compute_skew_change_z(series, as_of=date.today())
    assert z is None


def test_skew_change_z_empty_returns_none():
    """Empty series → None (D8 graceful)."""
    z = compute_skew_change_z(pd.Series([], dtype=float), as_of=date.today())
    assert z is None
