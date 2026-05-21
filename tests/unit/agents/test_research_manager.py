"""Research Manager (Stage 2) — EMA blend + hysteresis 단위 test.

C3 / spec §2 C3 / decisions.md D2, D3:
  - EMA blend (Issue #11): prior_research_decision 가 있으면 24-cell 분포 blend.
    λ=1.0 default → identity. λ<1.0 → blend.
  - Hysteresis: dominant_cycle 변경 시 Δ threshold. Δ=0.0 default → identity.
"""
import pytest

from tradingagents.agents.managers.research_manager import (
    _apply_hysteresis, _blend_with_prior,
)
from tradingagents.schemas.research import ALL_CELLS, ScenarioProbabilities24
from tradingagents.skills.research.scenario_mapper import map_probs_to_bucket


def _probs_for(cell: str, marg: float = 1.0) -> ScenarioProbabilities24:
    """Helper: target cell P=marg, 나머지 23 cell 균등 분포."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs[cell] = marg
    if marg < 1.0:
        remaining = (1.0 - marg) / (len(ALL_CELLS) - 1)
        for k in ALL_CELLS:
            if k != cell:
                kwargs[k] = remaining
    return ScenarioProbabilities24(**kwargs, reasoning="t")


# === _blend_with_prior — EMA ===


def test_blend_with_prior_none_returns_new_identity():
    """prior=None → new 그대로."""
    new = _probs_for("B_N_F", 0.80)
    result = _blend_with_prior(new, prior_decision=None, lam=0.5)
    assert result is new


def test_blend_with_lambda_one_returns_new_identity():
    """λ=1.0 → prior 무시 (no-op default)."""
    new = _probs_for("B_N_F", 0.80)
    prior = map_probs_to_bucket(_probs_for("A_N_F", 0.80))
    result = _blend_with_prior(new, prior_decision=prior, lam=1.0)
    assert result is new


def test_blend_with_lambda_zero_returns_prior_probs():
    """λ=0 → 100% prior. (boundary case — 정상 분포 보존)"""
    new = _probs_for("B_N_F", 0.80)
    prior = map_probs_to_bucket(_probs_for("A_N_F", 0.80))
    result = _blend_with_prior(new, prior_decision=prior, lam=0.0)
    # prior 가 A_N_F=0.80 dominant 였으므로
    assert result.A_N_F == pytest.approx(0.80, abs=1e-6)
    assert result.B_N_F == pytest.approx((1.0 - 0.80) / 23, abs=1e-6)


def test_blend_with_lambda_half_is_average():
    """λ=0.5 → new 와 prior 의 50:50 평균."""
    new = _probs_for("B_N_F", 0.80)
    prior = map_probs_to_bucket(_probs_for("A_N_F", 0.80))
    result = _blend_with_prior(new, prior_decision=prior, lam=0.5)
    # 둘 다 dominant cell 0.80, others (1-0.80)/23 ≈ 0.00870
    # blended: A_N_F = 0.5×0.00870 + 0.5×0.80 ≈ 0.4043
    # blended: B_N_F = 0.5×0.80 + 0.5×0.00870 ≈ 0.4043
    assert result.A_N_F == pytest.approx(result.B_N_F, abs=1e-4)
    assert result.A_N_F == pytest.approx(0.404, abs=0.005)


def test_blend_result_sums_to_one():
    """blend 후 24-cell 합 = 1.0 (renormalize)."""
    new = _probs_for("B_N_F", 0.80)
    prior = map_probs_to_bucket(_probs_for("D_T_stress", 0.50))
    result = _blend_with_prior(new, prior_decision=prior, lam=0.3)
    total = sum(getattr(result, k) for k in ALL_CELLS)
    assert total == pytest.approx(1.0, abs=1e-6)


def test_blend_preserves_new_reasoning():
    """blend 결과의 reasoning 은 new 쪽 유지 (prior 의 reasoning 아님)."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs["B_N_F"] = 1.0
    new = ScenarioProbabilities24(**kwargs, reasoning="new_reason_xyz")
    prior_kwargs = {k: 0.0 for k in ALL_CELLS}
    prior_kwargs["A_N_F"] = 1.0
    prior_probs = ScenarioProbabilities24(**prior_kwargs, reasoning="prior_reason")
    prior = map_probs_to_bucket(prior_probs)
    result = _blend_with_prior(new, prior_decision=prior, lam=0.5)
    assert result.reasoning == "new_reason_xyz"


# === _apply_hysteresis ===


def test_hysteresis_off_default_returns_identity():
    """Δ=0.0 → decision 그대로 (cycle 다르더라도)."""
    new = map_probs_to_bucket(_probs_for("B_N_F", 0.70))
    prior = map_probs_to_bucket(_probs_for("A_N_F", 0.70))
    result = _apply_hysteresis(new, prior_decision=prior, delta=0.0)
    assert result is new


def test_hysteresis_with_no_prior_returns_identity():
    new = map_probs_to_bucket(_probs_for("B_N_F", 0.70))
    result = _apply_hysteresis(new, prior_decision=None, delta=0.10)
    assert result is new


def test_hysteresis_same_dominant_returns_identity():
    """dominant_cycle 동일 → Δ 평가 없이 identity."""
    new = map_probs_to_bucket(_probs_for("B_N_F", 0.70))
    prior = map_probs_to_bucket(_probs_for("B_N_F", 0.85))  # 같은 B
    result = _apply_hysteresis(new, prior_decision=prior, delta=0.10)
    assert result is new


def test_hysteresis_override_when_change_below_delta():
    """new dominant=Y, prior dominant=X, (new_Y - new_X) < Δ → X 로 override."""
    # new: B 0.40, A 0.35, C 0.15, D 0.10 → dominant B 이지만 B-A 차이만 0.05
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({"B_N_F": 0.40, "A_N_F": 0.35, "C_N_F": 0.15, "D_N_F": 0.10})
    new = map_probs_to_bucket(ScenarioProbabilities24(**kwargs, reasoning="t"))
    prior = map_probs_to_bucket(_probs_for("A_N_F", 0.70))
    assert new.dominant_cycle == "B"
    result = _apply_hysteresis(new, prior_decision=prior, delta=0.10)
    # B-A diff = 0.05 < Δ=0.10 → A 유지
    assert result.dominant_cycle == "A"
    assert result.dominant_cycle_probability == pytest.approx(0.35, abs=1e-6)


def test_hysteresis_allows_change_when_above_delta():
    """new_Y - new_X ≥ Δ → change 허용."""
    # new: B 0.55, A 0.25, ...
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({"B_N_F": 0.55, "A_N_F": 0.25, "C_N_F": 0.10, "D_N_F": 0.10})
    new = map_probs_to_bucket(ScenarioProbabilities24(**kwargs, reasoning="t"))
    prior = map_probs_to_bucket(_probs_for("A_N_F", 0.70))
    assert new.dominant_cycle == "B"
    result = _apply_hysteresis(new, prior_decision=prior, delta=0.10)
    # B-A diff = 0.30 > Δ=0.10 → change 허용
    assert result.dominant_cycle == "B"
    assert result.dominant_cycle_probability == pytest.approx(0.55, abs=1e-6)
