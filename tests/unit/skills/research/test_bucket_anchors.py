"""Unit tests for Stage 2 bucket anchors (covenant composition)."""
from __future__ import annotations

import math

import pytest

from tradingagents.skills.portfolio.bl_views import SCENARIO_BUCKET_RULEBOOK
from tradingagents.skills.research.bucket_anchors import (
    SCENARIO_ANCHOR_KEYS,
    SCENARIO_BUCKET_ANCHORS,
    REGIME_BUCKET_ANCHORS,
    NON_RISK_BUCKETS,
    anchor_scenario_pure,
    apply_regime_modifiers,
    apply_scenario_real_caps,
    blend_bucket_anchors,
    compose_anchor_covenant,
    precious_cyclical_sum,
    risk_bucket_sum,
    thesis_tags,
    validate_anchor,
)
from tradingagents.skills.research.factor_to_bucket import BUCKETS, RISK_BUCKETS


@pytest.mark.parametrize("name, weights", [
    *[(q, REGIME_BUCKET_ANCHORS[q]) for q in REGIME_BUCKET_ANCHORS],
    *[(s, SCENARIO_BUCKET_ANCHORS[s]) for s in SCENARIO_BUCKET_ANCHORS],
])
def test_each_anchor_sums_to_one_and_passes_validate(name, weights):
    assert abs(sum(weights.values()) - 1.0) < 1e-9, name
    assert validate_anchor(weights), name
    assert risk_bucket_sum(weights) <= 0.70 + 1e-9, name


def test_scenario_keys_match_rulebook():
    assert set(SCENARIO_ANCHOR_KEYS) == set(SCENARIO_BUCKET_RULEBOOK.keys())


def test_goldilocks_precious_plus_cyclical_below_16pct_raw_scenario():
    w = SCENARIO_BUCKET_ANCHORS["goldilocks"]
    assert precious_cyclical_sum(w) < 0.16


def test_goldilocks_scenario_pure_cap_14pct():
    pure = anchor_scenario_pure("goldilocks")
    capped = apply_scenario_real_caps("goldilocks", pure, goldilocks_pc_cap=0.14)
    assert precious_cyclical_sum(capped) <= 0.14 + 1e-9


def test_growth_inflation_regime_cyclical_at_most_12pct():
    w = REGIME_BUCKET_ANCHORS["growth_inflation"]
    assert w["cyclical_commodity_fx"] <= 0.12 + 1e-9


def test_a8_scenario_pure_is_normalized_scenario_body():
    pure = anchor_scenario_pure("stagflation")
    ref = SCENARIO_BUCKET_ANCHORS["stagflation"]
    total = sum(ref.values())
    for b in BUCKETS:
        assert math.isclose(pure[b], ref[b] / total, abs_tol=1e-9)


def test_m3_regime_modifiers_clamp_two_pp_per_non_risk_bucket():
    pure = anchor_scenario_pure("goldilocks")
    capped = apply_scenario_real_caps("goldilocks", pure, goldilocks_pc_cap=0.14)
    covenant, audit = apply_regime_modifiers(
        capped, "growth_inflation", max_pp=0.02,
    )
    mods = audit["regime_modifiers_pp"]
    assert audit["layer"] == 0
    for b in NON_RISK_BUCKETS:
        assert abs(float(mods[b])) <= 2.0 + 1e-9
    for b in RISK_BUCKETS:
        assert b not in mods
    assert math.isclose(sum(covenant[b] for b in BUCKETS), 1.0, abs_tol=1e-9)


def test_compose_anchor_covenant_gi_goldilocks():
    covenant, pure, audit = compose_anchor_covenant(
        "growth_inflation", "goldilocks",
    )
    assert validate_anchor(covenant)
    assert precious_cyclical_sum(covenant) <= 0.14 + 1e-9
    assert audit["anchor_scenario_pure"] == pure
    assert risk_bucket_sum(covenant) <= 0.58 + 1e-6


def test_compose_renormalizes_to_one():
    covenant, _, _ = compose_anchor_covenant(
        "recession_inflation", "stagflation",
    )
    assert math.isclose(sum(covenant[b] for b in BUCKETS), 1.0, abs_tol=1e-9)


def test_unknown_scenario_falls_back_to_goldilocks_pure():
    pure = anchor_scenario_pure("not_a_scenario")
    gold = anchor_scenario_pure("goldilocks")
    for b in BUCKETS:
        assert math.isclose(pure[b], gold[b], abs_tol=1e-9)


def test_blend_bucket_anchors_matches_compose():
    blended = blend_bucket_anchors("growth_disinflation", "goldilocks")
    covenant, _, _ = compose_anchor_covenant("growth_disinflation", "goldilocks")
    for b in BUCKETS:
        assert math.isclose(blended[b], covenant[b], abs_tol=1e-9)


def test_thesis_tags_goldilocks_and_gi():
    tags = thesis_tags("growth_inflation", "goldilocks")
    assert "inflation_background" in tags
    assert "goldilocks_narrative" in tags
