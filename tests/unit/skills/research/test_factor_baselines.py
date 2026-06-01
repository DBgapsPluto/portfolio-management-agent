"""factor_baselines.py: LONG_RUN_BASELINE table + z_score helper 검증."""
from __future__ import annotations

import pytest

from tradingagents.skills.research.factor_baselines import (
    LONG_RUN_BASELINE,
    get_baseline,
    z_score,
)


_EXPECTED_FACTORS = {
    "F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
    "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol", "F8_valuation",
    "F9_market_dispersion",
}


def test_all_nine_factors_present() -> None:
    factors_in_table = {f for (f, _c) in LONG_RUN_BASELINE.keys()}
    missing = _EXPECTED_FACTORS - factors_in_table
    assert not missing, f"missing factor baselines: {missing}"


def test_z_score_basic() -> None:
    # gdpnow baseline = (2.0, 2.0). value 4 → (4-2)/2 = 1.0
    z = z_score(4.0, "F1_growth", "gdpnow")
    assert z == pytest.approx(1.0)


def test_z_score_missing_returns_none() -> None:
    assert z_score(1.0, "F99_does_not_exist", "unknown") is None
    assert get_baseline("F1_growth", "unknown_component") is None


def test_z_score_sd_zero_returns_none() -> None:
    # Direct check: any synthetic (mean, sd=0) → None via helper
    # (our table 자체에는 sd=0 없음 — 본 가드 는 helper 의 방어 logic 검증.)
    from tradingagents.skills.research import factor_baselines as fb

    # 임시 monkey-patch
    orig = fb.LONG_RUN_BASELINE.copy()
    try:
        fb.LONG_RUN_BASELINE[("FX_test", "zero_sd")] = (0.0, 0.0)
        assert fb.z_score(1.0, "FX_test", "zero_sd") is None
    finally:
        fb.LONG_RUN_BASELINE.clear()
        fb.LONG_RUN_BASELINE.update(orig)


def test_gpr_index_zscore_baseline_present() -> None:
    """Tier 0 (2026-05-28): geopolitical_surge → gpr_index_zscore (already z-scored externally).

    Baseline (0, 1): gpr_zscore_60m=2.0 → z=2.0 (passes through cleanly).
    """
    z = z_score(2.0, "F7_equity_vol", "gpr_index_zscore")
    assert z is not None
    assert z == pytest.approx(2.0), f"expected 2.0, got {z}"
    # geopolitical_surge baseline removed (Tier 0)
    assert z_score(25.0, "F7_equity_vol", "geopolitical_surge") is None
