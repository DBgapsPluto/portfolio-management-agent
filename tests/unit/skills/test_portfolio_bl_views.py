"""Unit tests for Phase 3b BL views adapter."""
import math
import pytest

from tradingagents.skills.portfolio.bl_views import (
    SCENARIO_BUCKET_RULEBOOK,
    BL_VIEW_MIN_CONFIDENCE,
)
from tradingagents.skills.portfolio.method_picker import _SCENARIO_METHOD


def test_rulebook_covers_all_scenarios():
    assert set(SCENARIO_BUCKET_RULEBOOK.keys()) == set(_SCENARIO_METHOD.keys())


def test_rulebook_returns_finite_decimals():
    for scenario, bucket_returns in SCENARIO_BUCKET_RULEBOOK.items():
        for bucket, ret in bucket_returns.items():
            assert math.isfinite(ret), f"{scenario}/{bucket}: {ret} not finite"
            assert -0.30 <= ret <= 0.30, f"{scenario}/{bucket}: {ret} out of range"


def test_rulebook_has_all_5_buckets():
    expected_buckets = {"kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf"}
    for scenario, bucket_returns in SCENARIO_BUCKET_RULEBOOK.items():
        assert set(bucket_returns.keys()) == expected_buckets, scenario


def test_min_confidence_floor_is_positive():
    assert 0.0 < BL_VIEW_MIN_CONFIDENCE < 1.0
