import pytest

from tradingagents.schemas.research import ScenarioProbabilities
from tradingagents.skills.research.scenario_definitions import SCENARIO_BUCKETS
from tradingagents.skills.research.scenario_mapper import (
    _classify_conviction, map_probs_to_bucket,
)


def _probs(goldilocks=0.0, ai_concentration=0.0, stagflation=0.0,
           broad_recession=0.0, global_credit=0.0, kr_boom=0.0, kr_stress=0.0,
           reasoning: str = "test") -> ScenarioProbabilities:
    return ScenarioProbabilities(
        goldilocks=goldilocks, ai_concentration=ai_concentration,
        stagflation=stagflation, broad_recession=broad_recession,
        global_credit=global_credit,
        kr_boom=kr_boom, kr_stress=kr_stress,
        reasoning=reasoning,
    )


def test_all_scenarios_pure_match_their_bucket():
    """단일 시나리오 확률 1.0 → 정확히 그 시나리오의 SCENARIO_BUCKETS과 일치."""
    for scenario in SCENARIO_BUCKETS:
        kwargs = {s: 0.0 for s in SCENARIO_BUCKETS}
        kwargs[scenario] = 1.0
        probs = _probs(**kwargs)
        decision = map_probs_to_bucket(probs)
        expected = SCENARIO_BUCKETS[scenario]
        bt = decision.bucket_target
        assert bt.kr_equity == pytest.approx(expected["kr_equity"], 1e-6)
        assert bt.global_equity == pytest.approx(expected["global_equity"], 1e-6)
        assert bt.fx_commodity == pytest.approx(expected["fx_commodity"], 1e-6)
        assert bt.bond == pytest.approx(expected["bond"], 1e-6)
        assert bt.cash_mmf == pytest.approx(expected["cash_mmf"], 1e-6)
        assert decision.dominant_scenario == scenario
        assert decision.dominant_probability == 1.0


def test_uniform_probabilities_average_buckets():
    """7개 시나리오 동일 확률 → SCENARIO_BUCKETS 산술 평균."""
    probs = _probs(**{s: 1 / 7 for s in SCENARIO_BUCKETS})
    decision = map_probs_to_bucket(probs)
    bt = decision.bucket_target
    expected_kr = sum(SCENARIO_BUCKETS[s]["kr_equity"] for s in SCENARIO_BUCKETS) / 7
    assert bt.kr_equity == pytest.approx(expected_kr, 1e-6)
    assert bt.total == pytest.approx(1.0, 1e-6)


def test_mandate_invariant_holds_for_arbitrary_distributions():
    """무작위 확률 분포에서도 위험자산 ≤ 0.70 보장 (선형 invariant)."""
    test_cases = [
        {"goldilocks": 1.0},
        {"ai_concentration": 1.0},  # 위험 0.70 경계
        {"kr_boom": 1.0},
        {"goldilocks": 0.5, "ai_concentration": 0.5},
        {"goldilocks": 0.6, "kr_boom": 0.4},  # 모두 위험 0.65~0.70
    ]
    for kwargs in test_cases:
        all_kwargs = {s: 0.0 for s in SCENARIO_BUCKETS}
        all_kwargs.update(kwargs)
        probs = _probs(**all_kwargs)
        decision = map_probs_to_bucket(probs)
        assert decision.bucket_target.risk_asset_weight <= 0.70 + 1e-6


def test_dominant_picked_correctly_when_tie_breaking():
    probs = _probs(goldilocks=0.4, ai_concentration=0.3, stagflation=0.3)
    decision = map_probs_to_bucket(probs)
    assert decision.dominant_scenario == "goldilocks"
    assert decision.dominant_probability == pytest.approx(0.4, 1e-6)


def test_conviction_high_at_45_or_above():
    assert _classify_conviction(0.45) == "high"
    assert _classify_conviction(0.60) == "high"


def test_conviction_medium_between_30_and_45():
    assert _classify_conviction(0.30) == "medium"
    assert _classify_conviction(0.44) == "medium"


def test_conviction_low_below_30():
    assert _classify_conviction(0.29) == "low"
    assert _classify_conviction(0.15) == "low"


def test_bucket_target_sums_to_one():
    probs = _probs(goldilocks=0.3, broad_recession=0.3, kr_boom=0.4)
    decision = map_probs_to_bucket(probs)
    assert decision.bucket_target.total == pytest.approx(1.0, 1e-6)


def test_credit_event_pure_yields_extreme_defensive():
    probs = _probs(global_credit=1.0)
    decision = map_probs_to_bucket(probs)
    bt = decision.bucket_target
    assert bt.risk_asset_weight == pytest.approx(0.20, 1e-6)
    assert bt.cash_mmf == pytest.approx(0.35, 1e-6)
    assert decision.conviction == "high"


def test_scenarios_pairwise_l1_distance_sufficient():
    """페어별 L1 distance가 의미있게 분리되어야 (모든 페어 ≥0.20)."""
    keys = list(SCENARIO_BUCKETS.keys())
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            wa, wb = SCENARIO_BUCKETS[a], SCENARIO_BUCKETS[b]
            l1 = sum(abs(wa[k] - wb[k]) for k in wa)
            assert l1 >= 0.20, f"{a} vs {b}: L1={l1:.2f} too small"
