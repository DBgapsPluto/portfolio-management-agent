"""시나리오 확률 → BucketTarget 결정적 매핑.

Phase 1: 단순 확률 가중 평균. Phase 3에서 threshold-based blending 추가 예정.
"""
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.research import (
    ConvictionLevel, ResearchDecision, ScenarioName, ScenarioProbabilities,
)
from tradingagents.skills.registry import register_skill
from tradingagents.skills.research.scenario_definitions import SCENARIO_BUCKETS


_CONVICTION_HIGH = 0.45
_CONVICTION_MEDIUM = 0.30


def _classify_conviction(max_prob: float) -> ConvictionLevel:
    if max_prob >= _CONVICTION_HIGH:
        return "high"
    if max_prob >= _CONVICTION_MEDIUM:
        return "medium"
    return "low"


def _renormalize(weights: dict[str, float]) -> dict[str, float]:
    """부동소수 오차 보정 — 합이 1.0이 되도록 정규화."""
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("All weights are non-positive")
    return {k: v / total for k, v in weights.items()}


@register_skill(name="map_scenarios_to_bucket", category="research")
def map_probs_to_bucket(
    probs: ScenarioProbabilities, rationale_seed: str = "",
) -> ResearchDecision:
    """Probability-weighted average of SCENARIO_BUCKETS.

    Invariant: SCENARIO_BUCKETS 모두 위험자산 ≤ 0.70이므로 선형 결합도 ≤ 0.70.
    """
    prob_dict = probs.as_dict()

    accumulator: dict[str, float] = {
        "kr_equity": 0.0, "global_equity": 0.0,
        "fx_commodity": 0.0, "bond": 0.0, "cash_mmf": 0.0,
    }
    for scenario, p in prob_dict.items():
        scenario_w = SCENARIO_BUCKETS[scenario]
        for asset, w in scenario_w.items():
            accumulator[asset] += p * w

    normalized = _renormalize(accumulator)

    dominant: ScenarioName = max(prob_dict, key=lambda s: prob_dict[s])  # type: ignore[arg-type]
    dominant_prob = prob_dict[dominant]
    conviction = _classify_conviction(dominant_prob)

    rationale = (
        f"Dominant: {dominant} ({dominant_prob:.0%}, {conviction} conviction). "
        f"{rationale_seed}"
    )[:500]

    bucket = BucketTarget(
        kr_equity=normalized["kr_equity"],
        global_equity=normalized["global_equity"],
        fx_commodity=normalized["fx_commodity"],
        bond=normalized["bond"],
        cash_mmf=normalized["cash_mmf"],
        rationale=rationale,
    )

    return ResearchDecision(
        bucket_target=bucket,
        scenario_probabilities=probs,
        dominant_scenario=dominant,
        dominant_probability=dominant_prob,
        conviction=conviction,
    )
