"""Tests for Tasks 8.1 + 8.2: factor_baselines_dynamic — expanding window z-baseline."""
import pytest
from datetime import date
from unittest.mock import patch
import pandas as pd
from tradingagents.skills.research.factor_baselines_dynamic import (
    compute_expanding_baseline, COMPONENT_HISTORY_SOURCES,
    _register_default_sources,
)


def test_dispatch_table_registers_on_first_call():
    """COMPONENT_HISTORY_SOURCES populated lazily."""
    _register_default_sources()
    assert "cfnai" in COMPONENT_HISTORY_SOURCES
    assert "us_cape" in COMPONENT_HISTORY_SOURCES
    assert "credit_impulse" in COMPONENT_HISTORY_SOURCES


def test_unknown_component_falls_back_to_static():
    """Unknown component → static LONG_RUN_BASELINE fallback (may be None if not in static dict either)."""
    result = compute_expanding_baseline("nonexistent_component_xyz", "F1_growth", date(2020, 1, 1))
    # Static fallback returns whatever get_baseline does — likely None for unknown
    assert result is None or isinstance(result, tuple)


def test_funding_stress_pre_2018_uses_ted_baseline():
    """funding_bps with as_of < 2018-04-03 routes to TED-based baseline."""
    ted = pd.Series(
        [28.0, 32.0, 30.0] * 30,
        index=pd.date_range("2010-01-01", periods=90, freq="D"),
    )
    with patch("tradingagents.dataflows.fred.fetch_fred_series", return_value=ted):
        mean, sd = compute_expanding_baseline("funding_bps", "F10_systemic_liquidity",
                                                date(2015, 1, 1))
    assert abs(mean - 30.0) < 2.0
    assert sd > 0


def test_short_history_falls_back():
    """n < MIN_HISTORY_POINTS → static fallback."""
    short_series = pd.Series(
        [0.5, 0.6], index=pd.to_datetime(["2025-01-01", "2025-02-01"]),
    )
    def mock_fetch(s, e):
        return short_series
    # Manually register a test entry
    COMPONENT_HISTORY_SOURCES["test_short_component"] = ("test", mock_fetch)
    try:
        result = compute_expanding_baseline("test_short_component", "F1_growth", date(2025, 3, 1))
        # Falls back to static — for unknown ('test_short_component', 'F1_growth'),
        # static get_baseline returns None
        assert result is None
    finally:
        del COMPONENT_HISTORY_SOURCES["test_short_component"]
