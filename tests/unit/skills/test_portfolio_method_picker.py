"""method_picker — deterministic (Stage 3 Phase A)."""
from types import SimpleNamespace

import pytest

from tradingagents.schemas.portfolio import OptimizationMethod
from tradingagents.skills.portfolio.method_picker import (
    MethodChoice, pick_optimization_method,
)


def _decision(scenario: str, conviction: str = "medium"):
    return SimpleNamespace(
        dominant_scenario=scenario, conviction=conviction,
    )


def test_extreme_systemic_forces_min_variance():
    out = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        systemic_score=8.5, systemic_regime="risk_off",
    )
    assert out.method == OptimizationMethod.MIN_VARIANCE
    assert "8" in out.reasoning


def test_scenario_global_credit_to_min_variance():
    out = pick_optimization_method(
        systemic_score=7.0, systemic_regime="risk_off",
        research_decision=_decision("global_credit"),
    )
    assert out.method == OptimizationMethod.MIN_VARIANCE


def test_scenario_stagflation_to_risk_parity():
    out = pick_optimization_method(
        regime_quadrant="growth_inflation", systemic_score=5.0,
        research_decision=_decision("stagflation", "medium"),
    )
    assert out.method == OptimizationMethod.RISK_PARITY


def test_scenario_goldilocks_to_hrp():
    out = pick_optimization_method(
        regime_quadrant="growth_disinflation", systemic_score=4.0,
        systemic_regime="risk_on",
        research_decision=_decision("goldilocks", "high"),
    )
    assert out.method == OptimizationMethod.HRP


def test_low_conviction_downgrades_hrp_to_risk_parity():
    out = pick_optimization_method(
        regime_quadrant="growth_disinflation", systemic_score=4.0,
        research_decision=_decision("goldilocks", "low"),
    )
    assert out.method == OptimizationMethod.RISK_PARITY


def test_recession_regime_to_min_variance_without_scenario():
    out = pick_optimization_method(
        regime_quadrant="recession_disinflation",
        systemic_score=6.0, systemic_regime="neutral",
    )
    assert out.method == OptimizationMethod.MIN_VARIANCE


def test_risk_off_systemic_to_min_variance():
    out = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        systemic_score=6.5, systemic_regime="risk_off",
    )
    assert out.method == OptimizationMethod.MIN_VARIANCE


def test_growth_inflation_to_risk_parity():
    out = pick_optimization_method(
        regime_quadrant="growth_inflation",
        systemic_score=5.0, systemic_regime="neutral",
    )
    assert out.method == OptimizationMethod.RISK_PARITY


def test_default_is_hrp():
    out = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        systemic_score=4.0, systemic_regime="risk_on",
    )
    assert out.method == OptimizationMethod.HRP


def test_kr_boom_high_conviction_hrp():
    out = pick_optimization_method(
        systemic_score=4.5,
        research_decision=_decision("kr_boom", "high"),
    )
    assert out.method == OptimizationMethod.HRP


def test_kr_stress_min_variance():
    out = pick_optimization_method(
        systemic_score=5.5,
        research_decision=_decision("kr_stress"),
    )
    assert out.method == OptimizationMethod.MIN_VARIANCE


def test_returns_method_choice_with_reasoning():
    out = pick_optimization_method(systemic_score=4.0)
    assert isinstance(out, MethodChoice)
    assert len(out.reasoning) > 0
    assert len(out.reasoning) <= 300


# === Issue #7: B cycle (overheating) ≠ stagflation, separate HRP processing ===


def test_method_picker_overheating_returns_hrp():
    """Issue #7: B cycle (growth+inflation) 은 stagflation 아니라 overheating.

    overheating 처방: equity tilt 살아있되 inflation 위험 분산 → HRP.
    (이전엔 "stagflation" mis-label → RISK_PARITY 잘못 트리거.)
    """
    out = pick_optimization_method(
        regime_quadrant="growth_inflation", systemic_score=5.0,
        research_decision=_decision("overheating", "high"),
    )
    assert out.method == OptimizationMethod.HRP
    assert "overheating" in out.reasoning.lower()


def test_method_picker_overheating_low_conviction_downgrade():
    """overheating + low conviction → 기존 HRP downgrade 룰로 RISK_PARITY."""
    out = pick_optimization_method(
        regime_quadrant="growth_inflation", systemic_score=5.0,
        research_decision=_decision("overheating", "low"),
    )
    # method_picker.py line 82-84: low conviction + HRP → RISK_PARITY 격하
    assert out.method == OptimizationMethod.RISK_PARITY


# ---------- Stage 3 audit (2026-05-26): degraded_inputs strict mode ----------


def test_degraded_inputs_forces_min_variance():
    """Stage 3 audit Task 0: regime + systemic 둘 다 sentinel → MIN_VARIANCE 강제.

    Stage 1 (Task 0) sentinel guard 의 propagation 끝지점. macro_quant /
    market_risk 가 fetch 실패로 staleness=99 객체 만들면 → allocator 가
    degraded_inputs=True 전달 → method_picker rule 0 발동.
    """
    out = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        research_decision=_decision("goldilocks", "medium"),
        degraded_inputs=True,
        regime_staleness=99,
        systemic_staleness=99,
    )
    assert out.method == OptimizationMethod.MIN_VARIANCE
    assert out.rule_fired == "degraded_inputs_strict"
    assert out.rule_index == 0
    assert "sentinel" in out.reasoning
    assert out.inputs["degraded_inputs"] is True
    assert out.inputs["regime_staleness"] == 99
    assert out.inputs["systemic_staleness"] == 99


def test_normal_staleness_does_not_trigger_strict_mode():
    """정상 stale (1-7d) 은 통과 — 둘 다 ≥99 일 때만 발동.

    Phase 3b: regime_confidence=0.8 ≥ BL_TRIGGER_CONFIDENCE=0.7 이므로 goldilocks 는
    bl_high_confidence rule(2) 로 BLACK_LITTERMAN 으로 전환됨. degraded_inputs rule(0) 은
    발동되지 않음 (정상 경로 통과 확인이 이 테스트의 핵심).
    """
    out = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        regime_confidence=0.8,
        systemic_score=5.0,
        systemic_regime="neutral",
        research_decision=_decision("goldilocks", "medium"),
        degraded_inputs=False,  # 정상 입력
        regime_staleness=3,
        systemic_staleness=2,
    )
    # degraded_inputs rule 0 발동 안 됨 (정상 경로)
    assert out.rule_fired != "degraded_inputs_strict"
    # Phase 3b: goldilocks + conf=0.8 → BL trigger (rule 2)
    assert out.method == OptimizationMethod.BLACK_LITTERMAN
    assert out.rule_fired == "bl_high_confidence"


def test_low_conviction_downgrade_attribution():
    """Stage 3 audit Task 2: HRP→RISK_PARITY downgrade 시 inputs_trace 기록."""
    out = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        systemic_score=5.0,
        research_decision=_decision("goldilocks", "low"),  # HRP → downgrade
    )
    assert out.method == OptimizationMethod.RISK_PARITY
    assert out.inputs.get("downgraded_from_hrp") is True


def test_named_const_present():
    """Stage 3 audit Task 0/2: SYSTEMIC_EXTREME_THRESHOLD const 존재."""
    from tradingagents.skills.portfolio import method_picker as mp
    assert hasattr(mp, "SYSTEMIC_EXTREME_THRESHOLD")
    assert mp.SYSTEMIC_EXTREME_THRESHOLD == 8.0
    assert hasattr(mp, "LOW_CONVICTION_HRP_DOWNGRADE")
    assert mp.LOW_CONVICTION_HRP_DOWNGRADE is True


# === Phase 3b: BL trigger rule tests ===

from tradingagents.skills.portfolio.method_picker import BL_TRIGGER_CONFIDENCE


def test_picker_bl_trigger_high_confidence_known_scenario():
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.8,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="goldilocks",
        conviction="high",
    )
    assert choice.method == OptimizationMethod.BLACK_LITTERMAN
    assert choice.rule_fired == "bl_high_confidence"
    assert choice.params == {"_bl_trigger": True}


def test_picker_bl_not_triggered_low_confidence():
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="goldilocks",
        conviction="high",
    )
    assert choice.method != OptimizationMethod.BLACK_LITTERMAN
    assert choice.rule_fired == "scenario_mapping"


def test_picker_bl_not_triggered_no_scenario():
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.9,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario=None,
        conviction="high",
    )
    assert choice.method != OptimizationMethod.BLACK_LITTERMAN


def test_picker_bl_trigger_precedes_scenario_mapping():
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=BL_TRIGGER_CONFIDENCE,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="goldilocks",
        conviction="high",
    )
    assert choice.method == OptimizationMethod.BLACK_LITTERMAN
