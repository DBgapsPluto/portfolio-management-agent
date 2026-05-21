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


def test_conviction_beta_always_one_option_a():
    """C3 / decisions.md D1: β=1.0 고정 (option A, sharpening 제거).

    이전: p_dom 별 β=1.0~2.80. 현재: 항상 1.0.
    근거: variance n=20 측정 (bond σ 0.3pp ≪ 3pp, flip 0%) — sharpening 자체 불필요.
    """
    for p_dom in (0.10, 0.25, 0.30, 0.40, 0.55, 0.70, 0.90, 1.0):
        assert _compute_conviction_beta(p_dom) == pytest.approx(1.0), \
            f"β must be 1.0 for p_dom={p_dom} (option A)"


def test_sharpen_helper_identity_at_beta_one():
    """β=1.0 일 때 _sharpen_cycle_marginal 은 input 을 그대로 반환 (identity).

    option A 채택 후 mapper 가 호출하는 _sharpen 의 사실상 유일한 path.
    """
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({
        "A_N_F": 0.30, "A_T_F": 0.10,
        "B_N_F": 0.40, "B_N_boom": 0.20,
    })
    sharp = _sharpen_cycle_marginal(kwargs, beta=1.0)
    for key in ALL_CELLS:
        assert sharp.get(key, 0) == pytest.approx(kwargs.get(key, 0), abs=1e-9)


def test_effective_equals_raw_under_option_a():
    """C3 / D1: β=1.0 고정 → effective marginal == raw marginal (모든 p_dom)."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    # high-conviction B (이전엔 β=2.20 으로 sharpening 됐던 case)
    kwargs.update({
        "A_N_F": 0.10, "B_N_F": 0.70, "C_N_F": 0.15, "D_N_F": 0.05,
    })
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    decision = map_probs_to_bucket(probs)
    assert decision.dominant_cycle == "B"
    assert decision.conviction_beta == pytest.approx(1.0)
    # effective == raw 모든 cycle 에서
    for c in ("A", "B", "C", "D"):
        assert decision.effective_cycle_marginals[c] == pytest.approx(
            decision.cycle_marginals[c], abs=1e-6,
        ), f"effective[{c}] != raw[{c}] under option A"


def test_sharpening_inactive_at_low_conviction():
    """p_dom < 0.30 이면 effective ≈ raw, β=1 — option A 와도 일관."""
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


# === Task C1: dominant_scenario mapping (B→overheating, D→stagflation) ===


def _make_decision_with_cycle_dominant(cycle: str, marg: float = 0.7):
    """Helper: dominant cycle 이 주어진 값인 ResearchDecision."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    cell = f"{cycle}_N_F"
    others = ["A_N_F", "B_N_F", "C_N_F", "D_N_F"]
    others.remove(cell)
    kwargs[cell] = marg
    remaining = (1.0 - marg) / len(others)
    for o in others:
        kwargs[o] = remaining
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    return map_probs_to_bucket(probs)


def test_dominant_scenario_A_is_goldilocks():
    d = _make_decision_with_cycle_dominant("A")
    assert d.dominant_scenario == "goldilocks"


def test_dominant_scenario_B_is_overheating_not_stagflation():
    """Issue #7 production bug fix: B=growth+inflation ≠ stagflation."""
    d = _make_decision_with_cycle_dominant("B")
    assert d.dominant_scenario == "overheating"


def test_dominant_scenario_C_is_broad_recession():
    d = _make_decision_with_cycle_dominant("C")
    assert d.dominant_scenario == "broad_recession"


def test_dominant_scenario_D_is_stagflation():
    d = _make_decision_with_cycle_dominant("D")
    assert d.dominant_scenario == "stagflation"


def test_dominant_scenario_tail_overrides_to_global_credit():
    """tail marginal ≥ 0.30 → global_credit (cycle 무관)."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    # B cycle 0.65, but tail T=0.35 from A_T_F 0.35
    kwargs.update({"B_N_F": 0.65, "A_T_F": 0.35})
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    d = map_probs_to_bucket(probs)
    assert d.dominant_scenario == "global_credit"


def test_dominant_scenario_kr_stress_override():
    """kr stress marginal ≥ 0.30 → kr_stress (cycle 무관)."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({"B_N_F": 0.40, "A_N_stress": 0.35, "C_N_stress": 0.25})
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    d = map_probs_to_bucket(probs)
    # tail marginal = 0 < 0.30, kr stress = 0.60 ≥ 0.30 → kr_stress
    assert d.dominant_scenario == "kr_stress"


def test_dominant_scenario_kr_boom_override():
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs.update({"A_N_F": 0.40, "A_N_boom": 0.35, "B_N_boom": 0.25})
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    d = map_probs_to_bucket(probs)
    assert d.dominant_scenario == "kr_boom"
