"""24-cell scenario mapper tests."""
import pytest

from tradingagents.schemas.research import (
    ALL_CELLS, CYCLE_CODES, ScenarioProbabilities24, cell_key, parse_cell_key,
)
from tradingagents.skills.research.scenario_definitions import (
    make_bond_tips_share, make_playbook,
)
from tradingagents.skills.research.scenario_mapper import (
    _classify_conviction, _compute_conviction_beta,
    _sharpen_cycle_marginal, map_probs_to_bucket,
)


def _probs_for_single_cell(target_cell: str, reasoning="t") -> ScenarioProbabilities24:
    """Set P=1.0 for target_cell, 0 for others."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs[target_cell] = 1.0
    return ScenarioProbabilities24(**kwargs, reasoning=reasoning)


def test_pure_single_cell_matches_its_playbook():
    """P=1.0 for one cell → BucketTarget = that cell's playbook."""
    for key in ALL_CELLS:
        probs = _probs_for_single_cell(key)
        decision = map_probs_to_bucket(probs)
        c, t, kr = parse_cell_key(key)
        expected = make_playbook(c, t, kr)
        bt = decision.bucket_target
        assert bt.kr_equity == pytest.approx(expected["kr_equity"], abs=1e-6)
        assert bt.global_equity == pytest.approx(expected["global_equity"], abs=1e-6)
        assert bt.fx_commodity == pytest.approx(expected["fx_commodity"], abs=1e-6)
        assert bt.bond == pytest.approx(expected["bond"], abs=1e-6)
        assert bt.cash_mmf == pytest.approx(expected["cash_mmf"], abs=1e-6)
        assert bt.bond_tips_share == pytest.approx(
            make_bond_tips_share(c, t, kr), abs=1e-6,
        )
        assert decision.dominant_cell.key == key
        assert decision.dominant_cell_probability == 1.0


def test_pure_single_cell_dominant_cycle_marginal():
    """Single cell P=1 → dominant_cycle = that cell's cycle."""
    decision = map_probs_to_bucket(_probs_for_single_cell("D_N_F"))
    assert decision.dominant_cycle == "D"
    assert decision.dominant_cycle_probability == 1.0
    assert decision.conviction == "high"


def test_uniform_24_cells_yields_average_bucket():
    """24개 균등 분포 → 24 playbook 산술 평균."""
    p_each = 1.0 / 24
    kwargs = {k: p_each for k in ALL_CELLS}
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    decision = map_probs_to_bucket(probs)
    # 모든 cycle marginal = 6/24 = 0.25
    for c in CYCLE_CODES:
        assert decision.cycle_marginals[c] == pytest.approx(0.25, abs=1e-6)
    assert decision.conviction == "low"  # 0.25 < 0.35
    assert decision.bucket_target.total == pytest.approx(1.0, abs=1e-6)


def test_mandate_invariant_holds_for_arbitrary_distributions():
    """무작위 확률 분포에서도 risk ≤ 0.70 (선형 invariant)."""
    test_cases = [
        {"A_N_F": 1.0},
        {"A_N_boom": 1.0},   # KR 70% but in A-N max equity 0.65, risk 0.70
        {"D_N_F": 1.0},      # stagflation
        {"A_N_F": 0.5, "D_N_F": 0.5},
        {"A_N_boom": 0.4, "C_T_F": 0.3, "D_N_F": 0.3},
    ]
    for kwargs in test_cases:
        all_kwargs = {k: 0.0 for k in ALL_CELLS}
        all_kwargs.update(kwargs)
        probs = ScenarioProbabilities24(**all_kwargs, reasoning="t")
        decision = map_probs_to_bucket(probs)
        assert decision.bucket_target.risk_asset_weight <= 0.70 + 1e-6


def test_dominant_cycle_picks_max_marginal_not_max_cell():
    """dominant_cycle은 cell이 아닌 D1 marginal 기준."""
    # A_N_boom 0.30, A_N_stress 0.20, D_N_F 0.40, C_N_F 0.10
    # → cycle A marginal = 0.50, cycle D = 0.40, cycle C = 0.10
    # dominant_cell = D_N_F (max 단일 cell), dominant_cycle = A (max marginal)
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({
        "A_N_boom": 0.30, "A_N_stress": 0.20, "D_N_F": 0.40, "C_N_F": 0.10,
    })
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    decision = map_probs_to_bucket(probs)
    assert decision.dominant_cell.key == "D_N_F"
    assert decision.dominant_cycle == "A"
    assert decision.dominant_cycle_probability == pytest.approx(0.50, abs=1e-6)


def test_conviction_thresholds():
    """conviction은 dominant_cycle_probability 기준."""
    assert _classify_conviction(0.55) == "high"
    assert _classify_conviction(0.70) == "high"
    assert _classify_conviction(0.35) == "medium"
    assert _classify_conviction(0.54) == "medium"
    assert _classify_conviction(0.34) == "low"
    assert _classify_conviction(0.20) == "low"


def test_bucket_target_sums_to_one():
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({"A_N_F": 0.3, "C_N_F": 0.3, "D_N_F": 0.4})
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    decision = map_probs_to_bucket(probs)
    assert decision.bucket_target.total == pytest.approx(1.0, abs=1e-6)


def test_tail_marginal_aggregates_correctly():
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({"A_N_F": 0.4, "C_T_F": 0.3, "D_T_F": 0.3})
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    decision = map_probs_to_bucket(probs)
    assert decision.tail_marginals["T"] == pytest.approx(0.60, abs=1e-6)
    assert decision.tail_marginals["N"] == pytest.approx(0.40, abs=1e-6)


def test_kr_marginal_aggregates_correctly():
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({
        "A_N_F": 0.30, "A_N_boom": 0.40, "A_N_stress": 0.30,
    })
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    decision = map_probs_to_bucket(probs)
    assert decision.kr_marginals["F"] == pytest.approx(0.30, abs=1e-6)
    assert decision.kr_marginals["boom"] == pytest.approx(0.40, abs=1e-6)
    assert decision.kr_marginals["stress"] == pytest.approx(0.30, abs=1e-6)


def test_conviction_beta_no_sharpen_below_threshold():
    """p_dom < 0.30 → β=1.0 (sharpening 비활성)."""
    assert _compute_conviction_beta(0.25) == pytest.approx(1.0)
    assert _compute_conviction_beta(0.30) == pytest.approx(1.0)
    assert _compute_conviction_beta(0.10) == pytest.approx(1.0)


def test_conviction_beta_increases_above_threshold():
    """p_dom 증가 시 β 증가 (sharpening 강화)."""
    assert _compute_conviction_beta(0.40) == pytest.approx(1.30, abs=0.01)
    assert _compute_conviction_beta(0.55) == pytest.approx(1.75, abs=0.01)
    assert _compute_conviction_beta(0.70) == pytest.approx(2.20, abs=0.01)


def test_sharpen_preserves_tail_kr_conditional():
    """β>1로 cycle marginal sharpen해도 P(tail, kr | cycle)은 동일해야."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    # A cycle: A_N_F 0.3, A_T_F 0.1 (A marginal 0.4)
    # B cycle: B_N_F 0.4, B_N_boom 0.2 (B marginal 0.6)
    kwargs.update({
        "A_N_F": 0.30, "A_T_F": 0.10,
        "B_N_F": 0.40, "B_N_boom": 0.20,
    })
    sharp = _sharpen_cycle_marginal(kwargs, beta=2.0)
    # A 내부 conditional: A_N_F was 0.30/0.40=0.75, A_T_F was 0.10/0.40=0.25
    new_a_marg = sharp["A_N_F"] + sharp["A_T_F"]
    new_b_marg = sharp["B_N_F"] + sharp["B_N_boom"]
    assert sharp["A_N_F"] / new_a_marg == pytest.approx(0.75, abs=1e-6)
    assert sharp["A_T_F"] / new_a_marg == pytest.approx(0.25, abs=1e-6)
    assert sharp["B_N_F"] / new_b_marg == pytest.approx(2/3, abs=1e-6)
    # B was bigger, so β=2 makes B even bigger
    assert new_b_marg > 0.6
    assert abs(new_a_marg + new_b_marg - 1.0) < 1e-6


def test_sharpening_makes_dominant_cycle_more_concentrated():
    """β>1로 sharpening 후 dominant cycle marginal 증가, others 감소."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({
        "A_N_F": 0.20, "B_N_F": 0.50, "C_N_F": 0.20, "D_N_F": 0.10,
    })
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    decision = map_probs_to_bucket(probs)
    # raw: B=0.50, after β=1.0+3×0.20=1.60: B^1.6 / Z
    assert decision.dominant_cycle == "B"
    assert decision.dominant_cycle_probability == pytest.approx(0.50, abs=1e-6)
    # effective B marginal > raw B marginal
    assert decision.effective_cycle_marginals["B"] > 0.50
    assert decision.conviction_beta > 1.0


def test_sharpening_inactive_at_low_conviction():
    """p_dom < 0.30이면 effective ≈ raw, β=1."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    # 4 cycle 균등 — dominant 0.25
    kwargs.update({"A_N_F": 0.25, "B_N_F": 0.25, "C_N_F": 0.25, "D_N_F": 0.25})
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    decision = map_probs_to_bucket(probs)
    assert decision.conviction_beta == pytest.approx(1.0)
    for c in ("A", "B", "C", "D"):
        assert decision.effective_cycle_marginals[c] == pytest.approx(
            decision.cycle_marginals[c], abs=1e-6,
        )


def test_scenario_probabilities_must_sum_to_one():
    """validator: 합이 1이 아니면 ValueError."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs["A_N_F"] = 0.5  # 합 = 0.5
    with pytest.raises(ValueError, match="sum to 1.0"):
        ScenarioProbabilities24(**kwargs, reasoning="t")
