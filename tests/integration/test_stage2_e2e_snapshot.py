"""Stage 2 e2e snapshot — C3 (β=1 + EMA + hysteresis) 적용 후 portfolio 영향 검증.

목적:
1. β=1 고정 (D1) 후 effective_cycle_marginals == cycle_marginals 가
   2026-05-15 시점 fixture 에서도 유지되는지.
2. EMA/hysteresis default (no-op) 가 prior_research_decision 있을 때도 raw 보존하는지.
3. mandate (위험자산 ≤ 0.70) 가 다양한 시나리오에서 깨지지 않는지.

Frozen fixture: 2026-05-15 baseline ablation (B=0.79, overheating) 의 cycle marginal
근사값 사용 — variance n=20 에서 관찰된 mean.
"""
import pytest

from tradingagents.agents.managers.research_manager import (
    _EMA_LAMBDA, _HYSTERESIS_DELTA, _apply_hysteresis, _blend_with_prior,
)
from tradingagents.schemas.research import ALL_CELLS, ScenarioProbabilities24
from tradingagents.skills.research.scenario_mapper import map_probs_to_bucket


@pytest.fixture
def frozen_scenario_probabilities_20260515():
    """2026-05-15 ablation baseline 의 average 와 유사한 24-cell 분포 (B=0.79).

    실제 LLM 출력 분포 — overheating regime 대표.
    """
    kwargs = {k: 0.0 for k in ALL_CELLS}
    # B cycle (overheating) dominant ~0.79
    kwargs.update({
        "B_N_F": 0.55, "B_N_boom": 0.10, "B_N_stress": 0.10,
        "B_T_F": 0.02, "B_T_boom": 0.01, "B_T_stress": 0.01,
        # A cycle (residual)
        "A_N_F": 0.03, "A_N_boom": 0.01, "A_N_stress": 0.01,
        # C cycle (residual)
        "C_N_F": 0.05, "C_N_stress": 0.03,
        # D cycle (residual)
        "D_N_F": 0.05, "D_N_stress": 0.03,
    })
    return ScenarioProbabilities24(**kwargs, reasoning="frozen 2026-05-15")


def test_c3_default_no_sharpening_effective_equals_raw(frozen_scenario_probabilities_20260515):
    """C3 D1 (β=1 고정) — 2026-05-15-like fixture 에서도 sharpening 효과 없음.

    이전: B raw 0.79 → β=2.38 → effective 0.99 (cross-effect 압살).
    현재: B raw 0.79 → β=1.00 → effective 0.79 (cross-effect 보존).
    """
    decision = map_probs_to_bucket(frozen_scenario_probabilities_20260515)
    assert decision.dominant_cycle == "B"
    assert decision.dominant_scenario == "overheating"
    assert decision.conviction_beta == pytest.approx(1.0)
    for c in ("A", "B", "C", "D"):
        assert decision.effective_cycle_marginals[c] == pytest.approx(
            decision.cycle_marginals[c], abs=1e-6,
        ), f"C3: effective[{c}] != raw[{c}] — sharpening 이 다시 켜졌나?"


def test_c3_mandate_invariant_holds_on_frozen_fixture(frozen_scenario_probabilities_20260515):
    """위험자산 ≤ 0.70 — C3 후에도 mandate 보존."""
    decision = map_probs_to_bucket(frozen_scenario_probabilities_20260515)
    assert decision.bucket_target.risk_asset_weight <= 0.70 + 1e-6
    # bucket sum = 1.0
    assert decision.bucket_target.total == pytest.approx(1.0, abs=1e-6)


def test_c3_ema_default_lambda_one_with_prior_is_noop(frozen_scenario_probabilities_20260515):
    """D2 default (λ=1.0) — prior 있어도 blend 결과 == new (identity)."""
    new = frozen_scenario_probabilities_20260515
    # prior: D cycle (stagflation) 가정 (cycle 다름 — 더 strict 한 test)
    prior_kwargs = {k: 0.0 for k in ALL_CELLS}
    prior_kwargs.update({"D_N_F": 0.60, "D_N_stress": 0.20, "C_N_F": 0.20})
    prior_probs = ScenarioProbabilities24(**prior_kwargs, reasoning="prior")
    prior_decision = map_probs_to_bucket(prior_probs)

    result = _blend_with_prior(new, prior_decision=prior_decision, lam=_EMA_LAMBDA)
    # λ=1.0 → identity (object identity)
    assert result is new


def test_c3_hysteresis_default_delta_zero_is_noop(frozen_scenario_probabilities_20260515):
    """D3 default (Δ=0) — cycle 바뀌어도 override 없음."""
    new_decision = map_probs_to_bucket(frozen_scenario_probabilities_20260515)
    # prior D cycle
    prior_kwargs = {k: 0.0 for k in ALL_CELLS}
    prior_kwargs.update({"D_N_F": 0.60, "D_N_stress": 0.20, "C_N_F": 0.20})
    prior_decision = map_probs_to_bucket(
        ScenarioProbabilities24(**prior_kwargs, reasoning="prior"),
    )
    assert prior_decision.dominant_cycle == "D"
    assert new_decision.dominant_cycle == "B"

    result = _apply_hysteresis(new_decision, prior_decision, delta=_HYSTERESIS_DELTA)
    # Δ=0 → identity (object identity)
    assert result is new_decision
    assert result.dominant_cycle == "B"


def test_c3_ema_with_lambda_half_blends_to_new(frozen_scenario_probabilities_20260515):
    """λ=0.5 explicit (non-default) — blend 가 실제로 동작."""
    new = frozen_scenario_probabilities_20260515
    prior_kwargs = {k: 0.0 for k in ALL_CELLS}
    prior_kwargs.update({"D_N_F": 0.60, "D_N_stress": 0.20, "C_N_F": 0.20})
    prior_decision = map_probs_to_bucket(
        ScenarioProbabilities24(**prior_kwargs, reasoning="prior"),
    )

    result = _blend_with_prior(new, prior_decision=prior_decision, lam=0.5)
    # 결과는 new ≠ result (object) 이고 24-cell 합 = 1
    assert result is not new
    total = sum(getattr(result, k) for k in ALL_CELLS)
    assert total == pytest.approx(1.0, abs=1e-6)
    # blended B marginal: 0.5×0.79 + 0.5×0 (prior 에 B 없음) = ~0.395
    blended = map_probs_to_bucket(result)
    # 여전히 B dominant 인지 (0.395 > D 의 0.5×0.80=0.40 정도) — 박빙
    # 보다 robust: B marginal 이 raw new B 의 50% 정도여야
    assert blended.cycle_marginals["B"] == pytest.approx(0.79 * 0.5, abs=0.05)
