"""Severity-gated aggregation tests."""
import pytest

from tradingagents.schemas.risk_overlay import LensConcern, RiskOverlayDelta
from tradingagents.skills.risk.severity_aggregator import (
    _decide_strength, aggregate_lens_concerns,
)


def _concern(lens, level, mult=1.0, ceilings=None, floors=None):
    return LensConcern(
        lens=lens, level=level,
        proposed_overlay=RiskOverlayDelta(
            risk_asset_multiplier=mult,
            weight_ceilings=ceilings or {},
            tail_hedge_floor=floors or {},
        ),
        evidence="test evidence",
    )


def test_strength_critical_two():
    s, _ = _decide_strength([
        _concern("tail_risk", "critical"),
        _concern("concentration", "critical"),
    ])
    assert s == 1.0


def test_strength_critical_one():
    s, _ = _decide_strength([
        _concern("tail_risk", "critical"),
        _concern("concentration", "low"),
        _concern("macro_conditional", "none"),
    ])
    assert s == 0.7


def test_strength_high_two():
    s, _ = _decide_strength([
        _concern("tail_risk", "high"),
        _concern("concentration", "high"),
        _concern("macro_conditional", "low"),
    ])
    assert s == 0.5


def test_strength_high_one():
    s, _ = _decide_strength([
        _concern("tail_risk", "high"),
        _concern("concentration", "low"),
        _concern("macro_conditional", "none"),
    ])
    assert s == 0.3


def test_strength_medium_two():
    s, _ = _decide_strength([
        _concern("tail_risk", "medium"),
        _concern("concentration", "medium"),
        _concern("macro_conditional", "low"),
    ])
    assert s == 0.2


def test_strength_zero_for_low_only():
    s, _ = _decide_strength([
        _concern("tail_risk", "low"),
        _concern("concentration", "none"),
        _concern("macro_conditional", "low"),
    ])
    assert s == 0.0


def test_aggregate_empty_returns_no_concerns():
    overlay = aggregate_lens_concerns([])
    assert overlay.is_empty()
    assert overlay.strength_applied == 0.0


def test_aggregate_low_only_archives_but_empty_constraints():
    overlay = aggregate_lens_concerns([
        _concern("tail_risk", "low", mult=0.85),
    ])
    assert overlay.is_empty()
    # lens_concerns는 archive에 보존
    assert len(overlay.lens_concerns) == 1


def test_aggregate_critical_applies_full_strength():
    overlay = aggregate_lens_concerns([
        _concern("tail_risk", "critical", mult=0.6),
        _concern("concentration", "critical",
                 ceilings={"A001": 0.10}),
    ])
    assert overlay.strength_applied == 1.0
    # multiplier: full strength → 0.6 그대로 (blended = 1.0 - (1-0.6)*1.0 = 0.6)
    assert overlay.risk_asset_multiplier == pytest.approx(0.6, abs=0.01)
    # ceiling: full strength → 0.10 그대로
    assert overlay.weight_ceilings.get("A001") == pytest.approx(0.10, abs=0.01)


def test_aggregate_high_one_relaxes_overlay():
    overlay = aggregate_lens_concerns([
        _concern("tail_risk", "high", mult=0.7,
                 floors={"A005": 0.10}),
    ])
    assert overlay.strength_applied == 0.3
    # multiplier: strength 0.3 → 1.0 - (1-0.7)*0.3 = 0.91
    assert overlay.risk_asset_multiplier == pytest.approx(0.91, abs=0.01)
    # floor: 0.10 × 0.3 = 0.03
    assert overlay.tail_hedge_floor.get("A005") == pytest.approx(0.03, abs=0.01)


def test_merge_takes_most_defensive_multiplier():
    overlay = aggregate_lens_concerns([
        _concern("tail_risk", "high", mult=0.6),
        _concern("concentration", "high", mult=0.8),
    ])
    # strength = 0.5 (high ≥2). multiplier blended:
    #   tail: 1.0 - (1-0.6)*0.5 = 0.80
    #   conc: 1.0 - (1-0.8)*0.5 = 0.90
    # min = 0.80
    assert overlay.risk_asset_multiplier == pytest.approx(0.80, abs=0.01)
