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
    views, confs, _ = generate_bl_views(
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
    # goldilocks view_conf_multi=1.3: 0.8*1.3=1.04 → clipped to 1.0
    assert all(c == BL_VIEW_CONF_MAX_AFTER_MULTI for c in confs)


def test_generate_bl_views_records_breakdown():
    candidates = {"kr_equity": ["A069500"], "bond": ["A148070", "A114260"]}
    breakdown: dict = {}
    views, confs, _ = generate_bl_views(
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
    views, _, _tilt = generate_bl_views(
        scenario="kr_boom",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert views["A1"] == views["A2"] == views["A3"] == 0.13


def test_generate_bl_views_unknown_scenario_returns_empty():
    breakdown: dict = {}
    views, confs, _ = generate_bl_views(
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
    views, confs, _ = generate_bl_views(
        scenario=None,
        regime_confidence=0.8,
        candidates={"kr_equity": ["A069500"]},
        breakdown_out=breakdown,
    )
    assert views == {}
    assert confs == []
    assert breakdown["fallback_reason"] == "unknown_scenario"


def test_generate_bl_views_confidence_floor():
    views, confs, _ = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.05,
        candidates={"kr_equity": ["A069500"]},
    )
    assert confs[0] >= BL_VIEW_MIN_CONFIDENCE


def test_generate_bl_views_bucket_agnostic():
    candidates = {
        "kr_equity":     ["A069500"],
        "alt_realestate": ["AXYZ"],
        "bond":          ["A148070"],
    }
    breakdown: dict = {}
    views, confs, _ = generate_bl_views(
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
    views, confs, _ = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates={},
    )
    assert views == {}
    assert confs == []


# ── Phase 4b: SCENARIO_BL_TILT + tilt_params tests ──────────────────────────

from tradingagents.skills.portfolio.bl_views import (
    SCENARIO_BL_TILT,
    BL_VIEW_CONF_MIN_AFTER_MULTI,
    BL_VIEW_CONF_MAX_AFTER_MULTI,
    BL_TAU_DEFAULT,
    BL_VIEW_CONF_MULTI_DEFAULT,
)


def test_scenario_bl_tilt_covers_all_scenarios():
    assert set(SCENARIO_BL_TILT.keys()) == set(SCENARIO_BUCKET_RULEBOOK.keys())


def test_scenario_bl_tilt_values_in_range():
    for scenario, tilt in SCENARIO_BL_TILT.items():
        assert 0.025 <= tilt["tau"] <= 0.10, f"{scenario}: τ={tilt['tau']}"
        assert 0.5 <= tilt["view_conf_multi"] <= 1.5, f"{scenario}: multi={tilt['view_conf_multi']}"


def test_generate_bl_views_returns_tilt_params():
    candidates = {"kr_equity": ["A069500"]}
    views, confs, tilt = generate_bl_views(
        scenario="goldilocks", regime_confidence=0.8, candidates=candidates,
    )
    assert "tau" in tilt
    assert "view_conf_multi" in tilt
    assert "view_conf_multi_applied" in tilt


def test_generate_bl_views_growth_scenario_high_tilt():
    candidates = {"kr_equity": ["A069500"]}
    _, _, tilt = generate_bl_views(
        scenario="goldilocks", regime_confidence=0.8, candidates=candidates,
    )
    assert tilt["tau"] == 0.10
    assert tilt["view_conf_multi"] == 1.3
    assert tilt["view_conf_multi_applied"] is True


def test_generate_bl_views_recession_scenario_low_tilt():
    candidates = {"bond": ["A148070"]}
    _, _, tilt = generate_bl_views(
        scenario="broad_recession", regime_confidence=0.8, candidates=candidates,
    )
    assert tilt["tau"] == 0.025
    assert tilt["view_conf_multi"] == 0.5
    assert tilt["view_conf_multi_applied"] is True


def test_generate_bl_views_view_conf_clipped_high():
    candidates = {"kr_equity": ["A069500", "A102110"]}
    _, confs, _ = generate_bl_views(
        scenario="goldilocks", regime_confidence=0.9, candidates=candidates,
    )
    assert all(c <= BL_VIEW_CONF_MAX_AFTER_MULTI + 1e-9 for c in confs)
    assert any(abs(c - 1.0) < 1e-6 for c in confs)


def test_generate_bl_views_view_conf_clipped_low():
    candidates = {"bond": ["A148070"]}
    _, confs, _ = generate_bl_views(
        scenario="broad_recession", regime_confidence=0.1, candidates=candidates,
    )
    assert all(BL_VIEW_CONF_MIN_AFTER_MULTI <= c <= BL_VIEW_CONF_MAX_AFTER_MULTI for c in confs)
    assert all(abs(c - 0.05) < 1e-6 for c in confs)


def test_generate_bl_views_records_tilt_in_breakdown():
    candidates = {"kr_equity": ["A069500"]}
    breakdown: dict = {}
    generate_bl_views(
        scenario="late_cycle", regime_confidence=0.5,
        candidates=candidates, breakdown_out=breakdown,
    )
    assert "tilt_params" in breakdown
    tp = breakdown["tilt_params"]
    assert tp["tau"] == 0.05
    assert tp["view_conf_multi"] == 0.8
    assert tp["view_conf_multi_applied"] is True
