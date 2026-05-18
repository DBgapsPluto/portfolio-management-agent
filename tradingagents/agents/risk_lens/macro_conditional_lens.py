"""Macro-conditional lens — Stage 3 weight가 시나리오에 적합한가 사후 검증.

LLM-free deterministic. Stage 3는 시나리오로부터 weight를 *생성*. 이 lens는
생성된 weight가 *현재 macro/risk 상태*에 맞는지 사후 검증.

Mismatch 케이스:
  - dominant_scenario=global_credit인데 위험자산 > 0.30 → high concern
  - dominant_scenario=broad_recession + systemic_score>7인데 위험자산 > 0.45 → medium
  - conviction=low이고 위험자산 > 0.60 → medium (불확실하면 보수)
  - regime=recession_disinflation인데 위험자산 > 0.50 → medium

Overlay:
  critical: risk_asset_multiplier = 0.65 (강한 defensive)
  high:     risk_asset_multiplier = 0.80
  medium:   risk_asset_multiplier = 0.92
  low/none: empty
"""
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.schemas.risk_overlay import LensConcern, RiskOverlayDelta


def _portfolio_risk_weight(wv: WeightVector, candidate_set) -> float:
    """위험자산(kr/global eq + fx_comm) bucket의 weight 합."""
    if candidate_set is None:
        return 0.0
    risk_buckets = {"kr_equity", "global_equity", "fx_commodity"}
    risk_tickers = {
        t for bucket, tickers in candidate_set.bucket_to_tickers.items()
        for t in tickers if bucket in risk_buckets
    }
    return sum(w for t, w in wv.weights.items() if t in risk_tickers)


def _classify(
    risk_weight: float, dominant_scenario: str | None, conviction: str | None,
    systemic_score: float, regime_quadrant: str | None,
) -> str:
    if dominant_scenario == "global_credit" and risk_weight > 0.30:
        return "critical"
    if dominant_scenario == "global_credit" and risk_weight > 0.20:
        return "high"

    if dominant_scenario in ("broad_recession", "kr_stress"):
        if systemic_score > 7.0 and risk_weight > 0.45:
            return "high"
        if risk_weight > 0.50:
            return "medium"

    if conviction == "low" and risk_weight > 0.60:
        return "medium"

    if regime_quadrant in ("recession_disinflation", "recession_inflation"):
        if risk_weight > 0.55:
            return "medium"
        if risk_weight > 0.65:
            return "high"

    return "none"


def _overlay_for_level(level: str) -> RiskOverlayDelta:
    if level == "critical":
        return RiskOverlayDelta(risk_asset_multiplier=0.65)
    if level == "high":
        return RiskOverlayDelta(risk_asset_multiplier=0.80)
    if level == "medium":
        return RiskOverlayDelta(risk_asset_multiplier=0.92)
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

    evidence = (
        f"risk_asset_weight={risk_weight*100:.1f}%, scenario={dominant}, "
        f"conviction={conviction}, systemic={systemic_score:.1f}, "
        f"regime={regime_quadrant}"
    )[:300]

    return LensConcern(
        lens="macro_conditional", level=level,  # type: ignore[arg-type]
        proposed_overlay=overlay, evidence=evidence,
    )
