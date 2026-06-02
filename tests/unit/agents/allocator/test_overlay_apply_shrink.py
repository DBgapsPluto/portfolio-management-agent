import pytest
from tradingagents.schemas.portfolio import WeightVector, OptimizationMethod
from tradingagents.schemas.risk_overlay import RiskOverlay
from tradingagents.agents.allocator.overlay_apply import apply_overlay_to_weights


def _wv():
    return WeightVector(
        method=OptimizationMethod.AUM_WEIGHTED,
        weights={"R1": 0.4, "R2": 0.3, "S1": 0.3},
        rationale="t",
    )


def test_empty_overlay_preserves_weights():
    wv = _wv()
    flags = {"R1": "위험", "R2": "위험", "S1": "안전"}
    out, changed = apply_overlay_to_weights(wv, RiskOverlay(), flags)
    assert not changed
    assert out.weights == wv.weights


def test_multiplier_shrinks_risk_redistributes_to_safe():
    wv = _wv()                       # 위험합 0.7
    flags = {"R1": "위험", "R2": "위험", "S1": "안전"}
    ov = RiskOverlay(risk_asset_multiplier=0.5)
    out, changed = apply_overlay_to_weights(wv, ov, flags)
    assert changed
    risk = out.weights["R1"] + out.weights["R2"]
    assert risk == pytest.approx(0.35, abs=1e-6)        # 0.7 * 0.5
    assert out.weights["S1"] == pytest.approx(0.65, abs=1e-6)
    assert sum(out.weights.values()) == pytest.approx(1.0)


def test_weight_ceiling_clips_and_renormalizes():
    wv = _wv()
    flags = {"R1": "위험", "R2": "위험", "S1": "안전"}
    ov = RiskOverlay(weight_ceilings={"R1": 0.2})
    out, changed = apply_overlay_to_weights(wv, ov, flags)
    assert out.weights["R1"] <= 0.2 + 1e-6
    assert sum(out.weights.values()) == pytest.approx(1.0)
