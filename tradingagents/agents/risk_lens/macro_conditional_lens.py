"""Macro-conditional lens — Stage 3 weight가 시나리오에 적합한가 사후 검증.

LLM-free deterministic. Stage 3는 시나리오로부터 weight를 *생성*. 이 lens는
생성된 weight가 *현재 macro/risk 상태*에 맞는지 사후 검증.

Mismatch 케이스:
  - global_credit + risk_weight > GLOBAL_CREDIT_CRITICAL=0.30 → critical
  - global_credit + risk_weight > GLOBAL_CREDIT_HIGH=0.20 → high
  - broad_recession/kr_stress + systemic > RECESSION_SYSTEMIC=7.0 + risk > RECESSION_HIGH=0.45 → high
  - broad_recession/kr_stress + risk_weight > RECESSION_MEDIUM=0.50 → medium
  - conviction=low + risk_weight > LOW_CONVICTION_MEDIUM=0.60 → medium
  - regime=recession_* + risk_weight > RECESSION_REGIME_HIGH=0.65 → high
  - regime=recession_* + risk_weight > RECESSION_REGIME_MEDIUM=0.55 → medium

Overlay (위험자산 multiplier):
  critical: MULTIPLIER_CRITICAL=0.65
  high:     MULTIPLIER_HIGH=0.80
  medium:   MULTIPLIER_MEDIUM=0.92
  low/none: empty
"""
import logging

from tradingagents.schemas.portfolio import WeightVector
from tradingagents.schemas.risk_overlay import LensConcern, RiskOverlayDelta

logger = logging.getLogger(__name__)


# Stage 4 audit (2026-05-26, Task 2): scenario × risk_weight threshold.
GLOBAL_CREDIT_CRITICAL: float = 0.30   # global_credit 위험자산 critical
GLOBAL_CREDIT_HIGH: float = 0.20
RECESSION_SYSTEMIC: float = 7.0        # broad_recession/kr_stress + systemic gate
RECESSION_HIGH: float = 0.45           # high concern under stressed systemic
RECESSION_MEDIUM: float = 0.50
LOW_CONVICTION_MEDIUM: float = 0.60    # conviction low + 60% 초과 위험
RECESSION_REGIME_HIGH: float = 0.65    # macro regime quadrant recession_*
RECESSION_REGIME_MEDIUM: float = 0.55

# Preset multiplier per level.
MULTIPLIER_CRITICAL: float = 0.65
MULTIPLIER_HIGH: float = 0.80
MULTIPLIER_MEDIUM: float = 0.92

# Risk bucket 정의 (factor_to_bucket 의 RISK_BUCKETS 와 일치).
RISK_BUCKETS_MC: frozenset[str] = frozenset({"kr_equity", "global_equity", "fx_commodity"})


def _portfolio_risk_weight(wv: WeightVector, candidate_set) -> float:
    """위험자산(kr/global eq + fx_comm) bucket의 weight 합."""
    if candidate_set is None:
        return 0.0
    risk_tickers = {
        t for bucket, tickers in candidate_set.bucket_to_tickers.items()
        for t in tickers if bucket in RISK_BUCKETS_MC
    }
    return sum(w for t, w in wv.weights.items() if t in risk_tickers)


def _classify(
    risk_weight: float, dominant_scenario: str | None, conviction: str | None,
    systemic_score: float, regime_quadrant: str | None,
) -> str:
    if dominant_scenario == "global_credit" and risk_weight > GLOBAL_CREDIT_CRITICAL:
        return "critical"
    if dominant_scenario == "global_credit" and risk_weight > GLOBAL_CREDIT_HIGH:
        return "high"

    if dominant_scenario in ("broad_recession", "kr_stress"):
        if systemic_score > RECESSION_SYSTEMIC and risk_weight > RECESSION_HIGH:
            return "high"
        if risk_weight > RECESSION_MEDIUM:
            return "medium"

    if conviction == "low" and risk_weight > LOW_CONVICTION_MEDIUM:
        return "medium"

    if regime_quadrant in ("recession_disinflation", "recession_inflation"):
        if risk_weight > RECESSION_REGIME_HIGH:
            return "high"
        if risk_weight > RECESSION_REGIME_MEDIUM:
            return "medium"

    return "none"


def _overlay_for_level(level: str) -> RiskOverlayDelta:
    if level == "critical":
        return RiskOverlayDelta(risk_asset_multiplier=MULTIPLIER_CRITICAL)
    if level == "high":
        return RiskOverlayDelta(risk_asset_multiplier=MULTIPLIER_HIGH)
    if level == "medium":
        return RiskOverlayDelta(risk_asset_multiplier=MULTIPLIER_MEDIUM)
    return RiskOverlayDelta()


def run_macro_conditional_lens(
    weight_vector: WeightVector,
    candidate_set,
    research_decision=None,
    systemic_score: float = 5.0,
    regime_quadrant: str | None = None,
) -> LensConcern:
    """Macro-conditional lens — weight × scenario/regime mismatch 검사."""
    risk_weight = _portfolio_risk_weight(weight_vector, candidate_set)

    dominant = getattr(research_decision, "dominant_scenario", None)
    conviction = getattr(research_decision, "conviction", None)

    level = _classify(
        risk_weight, dominant, conviction, systemic_score, regime_quadrant,
    )
    overlay = _overlay_for_level(level)
    logger.debug(
        "macro_conditional_lens: risk_weight=%.3f, scenario=%s, conviction=%s, "
        "systemic=%.1f, regime=%s → %s",
        risk_weight, dominant, conviction, systemic_score, regime_quadrant, level,
    )

    evidence = (
        f"risk_asset_weight={risk_weight*100:.1f}%, scenario={dominant}, "
        f"conviction={conviction}, systemic={systemic_score:.1f}, "
        f"regime={regime_quadrant}"
    )[:300]

    return LensConcern(
        lens="macro_conditional", level=level,  # type: ignore[arg-type]
        proposed_overlay=overlay, evidence=evidence,
    )
