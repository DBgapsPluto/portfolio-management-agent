"""compute_sector_dispersion tests (C7 — factor model F9 liquidity_regime component).

D7 pattern (기존 schema 확장): scalar return — analyst 가 BreadthSnapshot 의
sector_return_dispersion field 에 model_copy 로 채움.
D8 pattern: empty / single sector / exception → None (graceful skip).
D9 pattern: no retry, no cache in skill — fresh compute each call.
"""
import pytest

from tradingagents.skills.risk.sector_dispersion import compute_sector_dispersion


def test_dispersion_basic_equal_returns_zero():
    """All sectors with identical return → std = 0 (perfect concentration)."""
    sector_returns = {f"XL{c}": 0.05 for c in "FYBKVEUPMRC"}
    disp = compute_sector_dispersion(sector_returns)
    assert disp == pytest.approx(0.0, abs=1e-6)


def test_dispersion_wide_spread():
    """Wide cross-sectional spread → high dispersion."""
    sector_returns = {
        "XLF": +0.20, "XLE": -0.15, "XLV": +0.05,
        "XLY": +0.10, "XLU": -0.05,
    }
    disp = compute_sector_dispersion(sector_returns)
    assert disp > 0.05  # high dispersion


def test_dispersion_empty_returns_none():
    """Empty dict → None (D8 graceful)."""
    disp = compute_sector_dispersion({})
    assert disp is None


def test_dispersion_single_sector_returns_none():
    """1 sector — can't compute cross-sectional std."""
    disp = compute_sector_dispersion({"XLF": 0.10})
    assert disp is None
