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


from tradingagents.skills.portfolio.bl_views import generate_bl_views


def test_generate_bl_views_known_scenario_basic():
    candidates = {
        "kr_equity":     ["A069500", "A102110"],
        "global_equity": ["A360750"],
        "bond":          ["A148070"],
        "cash_mmf":      ["A130730"],
    }
    views, confs = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert views["A069500"] == 0.10
    assert views["A102110"] == 0.10
    assert views["A360750"] == 0.12
    assert views["A148070"] == 0.04
    assert views["A130730"] == 0.025
    assert len(views) == 5
    assert len(confs) == 5
    assert all(c == 0.8 for c in confs)


def test_generate_bl_views_records_breakdown():
    candidates = {"kr_equity": ["A069500"], "bond": ["A148070", "A114260"]}
    breakdown: dict = {}
    views, confs = generate_bl_views(
        scenario="late_cycle",
        regime_confidence=0.75,
        candidates=candidates,
        breakdown_out=breakdown,
    )
    assert breakdown["scenario"] == "late_cycle"
    assert breakdown["regime_confidence_raw"] == 0.75
    assert breakdown["confidence_used"] == 0.75
    assert breakdown["n_views_per_bucket"] == {"kr_equity": 1, "bond": 2}
    assert breakdown["rulebook_returns_used"] == {
        "kr_equity": 0.02, "bond": 0.06,
    }


def test_generate_bl_views_ticker_returns_match_bucket_rulebook():
    candidates = {"kr_equity": ["A1", "A2", "A3"]}
    views, _ = generate_bl_views(
        scenario="kr_boom",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert views["A1"] == views["A2"] == views["A3"] == 0.13


def test_generate_bl_views_unknown_scenario_returns_empty():
    breakdown: dict = {}
    views, confs = generate_bl_views(
        scenario="xyz_unknown",
        regime_confidence=0.8,
        candidates={"kr_equity": ["A069500"]},
        breakdown_out=breakdown,
    )
    assert views == {}
    assert confs == []
    assert breakdown["fallback_reason"] == "unknown_scenario"
    assert breakdown["scenario"] == "xyz_unknown"


def test_generate_bl_views_none_scenario_returns_empty():
    breakdown: dict = {}
    views, confs = generate_bl_views(
        scenario=None,
        regime_confidence=0.8,
        candidates={"kr_equity": ["A069500"]},
        breakdown_out=breakdown,
    )
    assert views == {}
    assert confs == []
    assert breakdown["fallback_reason"] == "unknown_scenario"


def test_generate_bl_views_confidence_floor():
    views, confs = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.05,
        candidates={"kr_equity": ["A069500"]},
    )
    assert confs[0] == BL_VIEW_MIN_CONFIDENCE


def test_generate_bl_views_bucket_agnostic():
    candidates = {
        "kr_equity":     ["A069500"],
        "alt_realestate": ["AXYZ"],
        "bond":          ["A148070"],
    }
    breakdown: dict = {}
    views, confs = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates=candidates,
        breakdown_out=breakdown,
    )
    assert "A069500" in views
    assert "A148070" in views
    assert "AXYZ" not in views
    assert "alt_realestate" not in breakdown["n_views_per_bucket"]


def test_generate_bl_views_empty_candidates():
    views, confs = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates={},
    )
    assert views == {}
    assert confs == []
