"""compute_yield_curve_extras tests — slope_5_30y derived (C4 — factor F4 component).

D7 pattern: scalar return (analyst applies model_copy on YieldCurveSnapshot).
D8 pattern: None input → None + logger.warning (no default fill, no raise).
D9 pattern: no retry / no cache in skill.
"""
from datetime import date

import pytest

from tradingagents.skills.macro.yield_curve import compute_yield_curve_extras


def test_slope_5_30y_basic():
    """DGS30 - DGS5 in basis points (pp diff * 100)."""
    slope = compute_yield_curve_extras(dgs5_pct=4.0, dgs30_pct=4.8, as_of=date.today())
    assert slope == pytest.approx(80.0)  # 0.8 pp → 80 bps


def test_slope_5_30y_inverted():
    """30y < 5y → negative slope."""
    slope = compute_yield_curve_extras(dgs5_pct=5.0, dgs30_pct=4.5, as_of=date.today())
    assert slope == pytest.approx(-50.0)


def test_slope_5_30y_none_dgs5_returns_none():
    """Missing 5y → None (D8 — graceful)."""
    slope = compute_yield_curve_extras(dgs5_pct=None, dgs30_pct=4.8, as_of=date.today())
    assert slope is None


def test_slope_5_30y_both_none_returns_none():
    """Both missing → None."""
    slope = compute_yield_curve_extras(dgs5_pct=None, dgs30_pct=None, as_of=date.today())
    assert slope is None
