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
