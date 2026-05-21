"""Optimization method picker — deterministic mapping (LLM 제거).

Stage 2 Phase 1 정신과 일관성 유지: regime + systemic + scenario 조합을
결정적 룰로 method를 선택. 100% 재현, 감사 가능, 비용 0.

Rule 우선순위:
  1. 극단 systemic risk (≥8) → MIN_VARIANCE
  2. Stage 2 dominant scenario (있으면 우선)
  3. Stage 1 macro regime quadrant
  4. systemic_regime (risk_on/off/neutral)
  5. Default → HRP
"""
from typing import Any

from pydantic import BaseModel, Field

from tradingagents.schemas.portfolio import OptimizationMethod
from tradingagents.skills.registry import register_skill


class MethodChoice(BaseModel):
    method: OptimizationMethod
    params: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = Field(max_length=300)


# 시나리오별 우선 method 룰. dominant_scenario 매칭 시 즉시 결정.
_SCENARIO_METHOD: dict[str, tuple[OptimizationMethod, str]] = {
    "global_credit":    (OptimizationMethod.MIN_VARIANCE,
                         "global_credit → 극단 defensive, min-vol 우선"),
    "broad_recession":  (OptimizationMethod.MIN_VARIANCE,
                         "broad_recession → defensive min-vol"),
    "kr_stress":        (OptimizationMethod.MIN_VARIANCE,
                         "kr_stress → KR 위기, defensive min-vol"),
    "stagflation":      (OptimizationMethod.RISK_PARITY,
                         "stagflation (recession+inflation) → 균형 분산, risk parity"),
    "overheating":      (OptimizationMethod.HRP,
                         "overheating (growth+inflation) → equity tilt + 분산, HRP"),
    "goldilocks":       (OptimizationMethod.HRP,
                         "goldilocks → 분산 친화, HRP"),
    "ai_concentration": (OptimizationMethod.HRP,
                         "ai_concentration → narrow leadership 위험, HRP로 corr 감안"),
    "kr_boom":          (OptimizationMethod.HRP,
                         "kr_boom → KR 호황 분산, HRP"),
}


@register_skill(name="pick_optimization_method", category="portfolio")
def pick_optimization_method(
    *,
    regime_quadrant: str | None = None,
    regime_confidence: float = 0.5,
    systemic_score: float = 5.0,
    systemic_regime: str = "neutral",
    research_decision=None,
    feedback: str = "",
) -> MethodChoice:
    """Deterministic method selection.

    research_decision: Stage 2 ResearchDecision (있으면 scenario·conviction 활용).
    feedback: D4 retry feedback string (logging만, decision에 영향 없음).
    """
    notes: list[str] = []
    if feedback:
        notes.append(f"retry context: {feedback[:80]}")

    # 1. 극단 systemic — 무조건 defensive
    if systemic_score >= 8.0:
        return MethodChoice(
            method=OptimizationMethod.MIN_VARIANCE,
            reasoning=(
                f"systemic_score {systemic_score:.1f} ≥ 8 → "
                "extreme risk-off, MIN_VARIANCE 강제."
            )[:300],
        )

    # 2. Stage 2 dominant scenario 우선
    if research_decision is not None:
        scenario = getattr(research_decision, "dominant_scenario", None)
        conviction = getattr(research_decision, "conviction", "medium")
        if scenario and scenario in _SCENARIO_METHOD:
            method, reason = _SCENARIO_METHOD[scenario]
            # conviction=low이고 risk-on 시나리오면 보수형으로 격하
            if conviction == "low" and method == OptimizationMethod.HRP:
                method = OptimizationMethod.RISK_PARITY
                reason = f"{scenario} but low conviction → risk_parity"
            return MethodChoice(
                method=method,
                reasoning=(
                    f"scenario={scenario}, conviction={conviction}: {reason}"
                )[:300],
            )

    # 3. macro regime quadrant
    if regime_quadrant in ("recession_disinflation", "recession_inflation"):
        return MethodChoice(
            method=OptimizationMethod.MIN_VARIANCE,
            reasoning=f"regime={regime_quadrant} → defensive MV.",
        )

    # 4. systemic risk regime
    if systemic_regime == "risk_off":
        return MethodChoice(
            method=OptimizationMethod.MIN_VARIANCE,
            reasoning=f"systemic_regime=risk_off (score={systemic_score:.1f}) → MV.",
        )

    if regime_quadrant == "growth_inflation":
        return MethodChoice(
            method=OptimizationMethod.RISK_PARITY,
            reasoning="growth_inflation → balanced risk_parity.",
        )

    # 5. Default — 분산 친화
    return MethodChoice(
        method=OptimizationMethod.HRP,
        reasoning=(
            f"default HRP (regime={regime_quadrant}, "
            f"systemic={systemic_score:.1f}/{systemic_regime})"
        )[:300],
    )
