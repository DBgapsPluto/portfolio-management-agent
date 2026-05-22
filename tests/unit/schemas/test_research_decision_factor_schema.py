"""ResearchDecision schema 의 factor model field 검증."""
import pytest
from tradingagents.schemas.research import (
    ResearchDecision, ScenarioProbabilities24, CellCoord, ALL_CELLS,
)
from tradingagents.schemas.portfolio import BucketTarget


def _minimal_research_decision_24cell(**override):
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs["B_N_F"] = 1.0
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    base = dict(
        bucket_target=BucketTarget(
            kr_equity=0.1, global_equity=0.2, fx_commodity=0.3,
            bond=0.3, cash_mmf=0.1, rationale="t", bond_tips_share=0.5,
        ),
        scenario_probabilities=probs,
        dominant_cell=CellCoord(cycle="B", tail="N", kr="F"),
        dominant_cell_probability=1.0,
        dominant_cycle="B",
        dominant_cycle_probability=1.0,
        cycle_marginals={"A": 0.0, "B": 1.0, "C": 0.0, "D": 0.0},
        tail_marginals={"N": 1.0, "T": 0.0},
        kr_marginals={"F": 1.0, "boom": 0.0, "stress": 0.0},
        conviction="high",
        conviction_beta=1.0,
        effective_cycle_marginals={"A": 0.0, "B": 1.0, "C": 0.0, "D": 0.0},
    )
    base.update(override)
    return ResearchDecision(**base)


def test_factor_scores_field_accepts_9_factor_dict():
    d = _minimal_research_decision_24cell(
        factor_scores={
            "F1_growth": 0.5, "F2_inflation": -0.3, "F3_real_rate": 0.1,
            "F4_term_premium": 0.0, "F5_credit_cycle": -0.2,
            "F6_krw_regime": 0.4, "F7_equity_vol_regime": 0.0,
            "F8_valuation": -0.5, "F9_liquidity_regime": 0.2,
        }
    )
    assert d.factor_scores["F1_growth"] == 0.5
    assert len(d.factor_scores) == 9


def test_factor_contributions_field_accepts_attribution():
    d = _minimal_research_decision_24cell(
        factor_contributions={
            "F1_growth": {"kr_equity": 0.01, "global_equity": 0.02,
                          "fx_commodity": 0.0, "bond": -0.02, "cash_mmf": -0.01},
        }
    )
    assert d.factor_contributions["F1_growth"]["global_equity"] == 0.02


def test_baseline_bucket_field_accepts_dict():
    d = _minimal_research_decision_24cell(
        baseline_bucket={"kr_equity": 0.12, "global_equity": 0.20,
                         "fx_commodity": 0.15, "bond": 0.33, "cash_mmf": 0.20}
    )
    assert d.baseline_bucket["bond"] == 0.33


def test_safety_diagnostics_field_accepts_dict():
    d = _minimal_research_decision_24cell(
        safety_diagnostics={
            "pre_projection_risk_asset": 0.65,
            "mandate_violated_pre_projection": False,
            "extreme_factor_active": False,
            "projection_l2_distance": 0.0,
            "projection_intervened": False,
        }
    )
    assert d.safety_diagnostics["projection_l2_distance"] == 0.0


def test_factor_field_defaults_empty():
    d = _minimal_research_decision_24cell()
    assert d.factor_scores == {}
    assert d.factor_contributions == {}
    assert d.baseline_bucket == {}
    assert d.safety_diagnostics == {}
