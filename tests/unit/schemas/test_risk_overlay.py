"""RiskOverlay schema + RiskOverlayDelta + LensConcern."""
from datetime import date

import pytest
from pydantic import ValidationError

from tradingagents.schemas.risk_overlay import (
    LensConcern, RiskOverlay, RiskOverlayDelta,
)


def test_overlay_delta_default_is_empty():
    d = RiskOverlayDelta()
    assert d.weight_ceilings == {}
    assert d.cluster_caps == {}
    assert d.risk_asset_multiplier == 1.0
    assert d.tail_hedge_floor == {}


def test_overlay_multiplier_range():
    RiskOverlayDelta(risk_asset_multiplier=0.5)
    RiskOverlayDelta(risk_asset_multiplier=1.0)
    with pytest.raises(ValidationError):
        RiskOverlayDelta(risk_asset_multiplier=0.4)  # < 0.5
    with pytest.raises(ValidationError):
        RiskOverlayDelta(risk_asset_multiplier=1.1)  # > 1.0


def test_lens_concern_requires_evidence():
    LensConcern(
        lens="tail_risk", level="high",
        proposed_overlay=RiskOverlayDelta(risk_asset_multiplier=0.85),
        evidence="CVaR 95% = -4.2%, threshold -3.5% 초과",
    )


def test_lens_concern_lens_enum_only():
    with pytest.raises(ValidationError):
        LensConcern(lens="random", level="high", evidence="x")


def test_overlay_is_empty():
    assert RiskOverlay().is_empty()
    assert not RiskOverlay(risk_asset_multiplier=0.9).is_empty()
    assert not RiskOverlay(weight_ceilings={"A001": 0.15}).is_empty()
    assert not RiskOverlay(cluster_caps={"c1": 0.30}).is_empty()
    assert not RiskOverlay(tail_hedge_floor={"A001": 0.03}).is_empty()


def test_no_concerns_factory():
    o = RiskOverlay.no_concerns(as_of_date=date(2026, 5, 18))
    assert o.is_empty()
    assert o.strength_applied == 0.0
    assert "no concerns" in o.severity_decision.lower()


def test_overlay_strength_in_range():
    RiskOverlay(strength_applied=0.0)
    RiskOverlay(strength_applied=1.0)
    with pytest.raises(ValidationError):
        RiskOverlay(strength_applied=1.5)


def test_risk_overlay_has_outcome_field_with_default():
    """RiskOverlay 에 overlay_apply_outcome 신규 필드, default='primary_success'."""
    from tradingagents.schemas.risk_overlay import RiskOverlay

    overlay = RiskOverlay.no_concerns()
    assert overlay.overlay_apply_outcome == "primary_success"

    overlay2 = RiskOverlay(overlay_apply_outcome="relax_band")
    assert overlay2.overlay_apply_outcome == "relax_band"


def test_risk_overlay_outcome_literal_validation():
    """overlay_apply_outcome 은 정해진 5 값만 허용."""
    import pytest
    from pydantic import ValidationError
    from tradingagents.schemas.risk_overlay import RiskOverlay

    with pytest.raises(ValidationError):
        RiskOverlay(overlay_apply_outcome="invalid_value")
