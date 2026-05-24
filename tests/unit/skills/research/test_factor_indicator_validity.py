"""factor_reliability_audit.py: audit table 의 staleness + completeness + monotonicity."""
from __future__ import annotations

from datetime import date

import pytest

from tradingagents.skills.research.factor_reliability_audit import (
    AUDIT_DATE,
    COMPONENT_RELIABILITY,
    WEIGHT_CAP_BY_RELIABILITY,
    get_reliability,
    get_weight_cap,
)


EXPECTED_COMPONENTS: frozenset[str] = frozenset({
    # F1
    "gdpnow", "cfnai", "cfnai_3m", "nfci", "sahm", "curve",  # ★ C8 (2026-05-24): cfnai_3m
    "release_surprise", "hawkish_bias", "macro_sent", "risk_regime_overnight",
    # F2
    "cpi_yoy", "cpi_3m", "core_pce", "five_y_five_y", "michigan_1y",
    "real_yield_inv", "fed_path_bps", "release_hawkish",
    # F3
    "tips_yield", "fed_voting_balance", "fed_path_implied",
    # F4
    "slope_2_10y", "slope_5_30y", "fed_tone_balance",
    # F5
    "hy_oas_bps", "hy_oas_momentum", "credit_quality_bps", "funding_bps",
    "corporate_distress", "dovish_bias",
    # F6
    "krw_overnight_pct", "krw_level", "krw_reer", "kr_us_rate_diff",
    "foreign_flow_z", "kr_exports_yoy", "bok_tone_balance",
    # F7
    "vix_level", "vix_z_score", "vix_term_ratio", "move",
    "realized_vol_60d", "skew_level", "skew_change",
    "sentiment_dispersion", "geopolitical_surge",
    # F8
    "sp_pe", "earnings_yield", "erp", "kospi_pbr",
    # F9
    "vrp", "eq_bond_corr", "sector_dispersion", "breadth",
    "event_cluster", "rising_signal",
})


def test_audit_date_is_current() -> None:
    """6 month 초과 시 fail → 재검증 강제."""
    audit = date.fromisoformat(AUDIT_DATE)
    days_since = (date.today() - audit).days
    assert days_since <= 180, (
        f"Audit table 가 {days_since}d 전 — 재검증 필요 (≤180d)."
    )


def test_all_components_have_reliability() -> None:
    missing = EXPECTED_COMPONENTS - set(COMPONENT_RELIABILITY.keys())
    assert not missing, f"audit table 누락 components: {missing}"


def test_weight_cap_monotone() -> None:
    tiers = ["high", "medium-high", "medium", "medium-low", "low", "uncertain"]
    caps = [WEIGHT_CAP_BY_RELIABILITY[t] for t in tiers]
    assert caps == sorted(caps, reverse=True), (
        f"weight cap 가 reliability tier 순으로 단조감소 아님: {caps}"
    )


def test_low_reliability_capped() -> None:
    assert WEIGHT_CAP_BY_RELIABILITY["medium-low"] <= 0.15
    assert WEIGHT_CAP_BY_RELIABILITY["low"] <= 0.15
    assert WEIGHT_CAP_BY_RELIABILITY["uncertain"] == 0.0


def test_get_reliability_default_low() -> None:
    """알 수 없는 component → 보수적 'low'."""
    assert get_reliability("__not_in_table__") == "low"
    assert get_weight_cap("__not_in_table__") == WEIGHT_CAP_BY_RELIABILITY["low"]
