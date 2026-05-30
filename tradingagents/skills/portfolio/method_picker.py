"""Optimization method picker — deterministic mapping (LLM 제거).

Stage 2 Phase 1 정신과 일관성 유지: regime + systemic + scenario 조합을
결정적 룰로 method를 선택. 100% 재현, 감사 가능, 비용 0.

Rule 우선순위:
  0. degraded_inputs (regime + systemic 둘 다 sentinel) → MIN_VARIANCE 강제
     (Stage 3 audit Task 0, 2026-05-26)
  1. 극단 systemic risk (≥SYSTEMIC_EXTREME_THRESHOLD) → MIN_VARIANCE
  2. Stage 2 dominant scenario (있으면 우선)
  3. Stage 1 macro regime quadrant
  4. systemic_regime (risk_on/off/neutral)
  5. Default → NCO
"""
import logging
from typing import Any

from pydantic import BaseModel, Field

from tradingagents.schemas.portfolio import OptimizationMethod
from tradingagents.skills.portfolio.bl_views import SCENARIO_BUCKET_RULEBOOK
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


# Stage 3 audit (2026-05-26, Task 2): named const.
# 8.0/10 = institutional risk-off 기준 (e.g. VIX>30 + 기타 신호 다중 confirmed).
SYSTEMIC_EXTREME_THRESHOLD: float = 8.0
# Phase 3b: regime_confidence 가 이 임계치 이상이고 알려진 scenario 가 있으면
# BL views 어댑터를 통해 BLACK_LITTERMAN 으로 전환 (scenario_mapping 보다 우선).
BL_TRIGGER_CONFIDENCE: float = 0.7


class MethodChoice(BaseModel):
    method: OptimizationMethod
    params: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = Field(max_length=300)
    # Attribution fields — which deterministic rule fired and what inputs it saw.
    # Backward-compat: existing archives lacking these fields rehydrate cleanly.
    rule_fired: str | None = None
    rule_index: int | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)


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
    "overheating":      (OptimizationMethod.NCO,
                         "overheating (growth+inflation) → equity tilt + 분산, NCO"),
    "goldilocks":       (OptimizationMethod.NCO,
                         "goldilocks → 분산 친화, NCO"),
    # 2026-05-26 #5 fix — late_cycle + sticky inflation cell.
    # 신용 약세 + 인플레 잔존 → equity tilt 자제, risk parity 로 균형 분산.
    "late_cycle":       (OptimizationMethod.RISK_PARITY,
                         "late_cycle (sticky inflation + credit fatigue) → 균형 분산"),
    "ai_concentration": (OptimizationMethod.NCO,
                         "ai_concentration → narrow leadership 위험, NCO로 corr 감안"),
    "kr_boom":          (OptimizationMethod.NCO,
                         "kr_boom → KR 호황 분산, NCO"),
}


@register_skill(name="pick_optimization_method", category="portfolio")
def pick_optimization_method(
    *,
    regime_quadrant: str | None = None,
    regime_confidence: float = 0.5,
    systemic_score: float = 5.0,
    systemic_regime: str = "neutral",
    research_decision=None,
    dominant_scenario: str | None = None,
    conviction: str | None = None,
    feedback: str = "",
    degraded_inputs: bool = False,
    regime_staleness: int | None = None,
    systemic_staleness: int | None = None,
) -> MethodChoice:
    """Deterministic method selection.

    research_decision: Stage 2 ResearchDecision (있으면 scenario·conviction 활용).
    dominant_scenario, conviction: research_decision 없이 직접 전달 가능
        (research_decision 이 있으면 그 쪽이 우선).
    feedback: D4 retry feedback string (logging만, decision에 영향 없음).
    degraded_inputs: Stage 3 audit Task 0 — regime + systemic 둘 다 sentinel(staleness≥99)
        인 경우 True. rule 0 가 발동되어 MIN_VARIANCE 강제 (fail-safe).
    regime_staleness, systemic_staleness: inputs_trace 기록용. attribution 가시화.
    """
    if research_decision is not None:
        scenario_in = getattr(research_decision, "dominant_scenario", None)
        conviction_in = getattr(research_decision, "conviction", "medium")
    else:
        scenario_in = dominant_scenario
        conviction_in = conviction
    inputs_trace: dict[str, Any] = {
        "regime_quadrant":     regime_quadrant,
        "regime_confidence":   regime_confidence,
        "systemic_score":      systemic_score,
        "systemic_regime":     systemic_regime,
        "dominant_scenario":   scenario_in,
        "conviction":          conviction_in,
        "feedback_present":    bool(feedback),
        "degraded_inputs":     degraded_inputs,
        "regime_staleness":    regime_staleness,
        "systemic_staleness":  systemic_staleness,
    }

    # 0. Stage 3 audit (2026-05-26, Task 0): regime + systemic 둘 다 fetch 실패
    # (sentinel staleness≥99) → 모든 downstream 결정이 placeholder 값에 의존.
    # fail-safe: MIN_VARIANCE 강제. 정상 1-7d stale 은 통과.
    if degraded_inputs:
        choice = MethodChoice(
            method=OptimizationMethod.MIN_VARIANCE,
            reasoning=(
                "degraded_inputs=True: regime+systemic 둘 다 sentinel "
                f"(staleness regime={regime_staleness}, systemic={systemic_staleness}) "
                "→ defensive MIN_VARIANCE 강제 (fail-safe)."
            )[:300],
            rule_fired="degraded_inputs_strict",
            rule_index=0,
            inputs=inputs_trace,
        )
        logger.warning(
            "method_picker rule 0 fired (degraded_inputs): regime + systemic 둘 다 "
            "sentinel → MIN_VARIANCE 강제. staleness regime=%s, systemic=%s",
            regime_staleness, systemic_staleness,
        )
        return choice

    # 1. 극단 systemic — 무조건 defensive
    if systemic_score >= SYSTEMIC_EXTREME_THRESHOLD:
        choice = MethodChoice(
            method=OptimizationMethod.MIN_VARIANCE,
            reasoning=(
                f"systemic_score {systemic_score:.1f} ≥ {SYSTEMIC_EXTREME_THRESHOLD} → "
                "extreme risk-off, MIN_VARIANCE 강제."
            )[:300],
            rule_fired="systemic_extreme",
            rule_index=1,
            inputs=inputs_trace,
        )
        logger.info(
            "method_picker rule 1 (systemic_extreme): score=%.1f → MIN_VARIANCE",
            systemic_score,
        )
        return choice

    # 2. Phase 3b: Black-Litterman trigger — scenario_mapping 보다 먼저 평가.
    if (
        scenario_in
        and regime_confidence >= BL_TRIGGER_CONFIDENCE
        and scenario_in in SCENARIO_BUCKET_RULEBOOK
    ):
        choice = MethodChoice(
            method=OptimizationMethod.BLACK_LITTERMAN,
            reasoning=(
                f"regime_confidence={regime_confidence:.2f} ≥ "
                f"{BL_TRIGGER_CONFIDENCE}, scenario={scenario_in}: "
                f"BL views from rulebook."
            )[:300],
            rule_fired="bl_high_confidence",
            rule_index=2,
            inputs=inputs_trace,
            params={"_bl_trigger": True},
        )
        logger.info(
            "method_picker rule 2 (bl_high_confidence): conf=%.2f scenario=%s → BL",
            regime_confidence, scenario_in,
        )
        return choice

    # 3. Stage 2 dominant scenario 우선
    if scenario_in and scenario_in in _SCENARIO_METHOD:
        method, reason = _SCENARIO_METHOD[scenario_in]
        choice = MethodChoice(
            method=method,
            reasoning=(
                f"scenario={scenario_in}, conviction={conviction_in}: {reason}"
            )[:300],
            rule_fired="scenario_mapping",
            rule_index=3,
            inputs=inputs_trace,
        )
        logger.info(
            "method_picker rule 3 (scenario=%s, conviction=%s) → %s",
            scenario_in, conviction_in, method.value,
        )
        return choice

    # 4. macro regime quadrant (recession)
    if regime_quadrant in ("recession_disinflation", "recession_inflation"):
        choice = MethodChoice(
            method=OptimizationMethod.MIN_VARIANCE,
            reasoning=f"regime={regime_quadrant} → defensive MV.",
            rule_fired="regime_recession",
            rule_index=4,
            inputs=inputs_trace,
        )
        logger.info(
            "method_picker rule 4 (regime=%s) → MIN_VARIANCE", regime_quadrant,
        )
        return choice

    # 5. systemic risk regime
    if systemic_regime == "risk_off":
        choice = MethodChoice(
            method=OptimizationMethod.MIN_VARIANCE,
            reasoning=f"systemic_regime=risk_off (score={systemic_score:.1f}) → MV.",
            rule_fired="systemic_risk_off",
            rule_index=5,
            inputs=inputs_trace,
        )
        logger.info(
            "method_picker rule 5 (systemic_regime=risk_off, score=%.1f) → MIN_VARIANCE",
            systemic_score,
        )
        return choice

    if regime_quadrant == "growth_inflation":
        choice = MethodChoice(
            method=OptimizationMethod.RISK_PARITY,
            reasoning="growth_inflation → balanced risk_parity.",
            rule_fired="regime_growth_inflation",
            rule_index=6,
            inputs=inputs_trace,
        )
        logger.info(
            "method_picker rule 6 (regime=growth_inflation) → RISK_PARITY",
        )
        return choice

    # 7. Default — 분산 친화
    choice = MethodChoice(
        method=OptimizationMethod.NCO,
        reasoning=(
            f"default NCO (regime={regime_quadrant}, "
            f"systemic={systemic_score:.1f}/{systemic_regime})"
        )[:300],
        rule_fired="default",
        rule_index=7,
        inputs=inputs_trace,
    )
    logger.info(
        "method_picker rule 7 (default, regime=%s, systemic=%.1f/%s) → NCO",
        regime_quadrant, systemic_score, systemic_regime,
    )
    return choice
