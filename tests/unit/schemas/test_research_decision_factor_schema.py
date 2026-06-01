"""ResearchDecision schema 의 factor model field 검증.

C5 (2026-05-23): 24-cell schema 제거 후 — bucket_target / conviction /
dominant_scenario + factor_* field 만 존재.
"""
from tradingagents.schemas.research import ResearchDecision
from tradingagents.schemas.portfolio import BucketTarget


def _minimal_research_decision(**override):
    """Factor model 만 (C5: 24-cell field 제거 후)."""
    base = dict(
        bucket_target=BucketTarget(
            weights={
                "kr_equity": 0.10, "global_equity": 0.20, "precious_metals": 0.05,
                "cyclical_commodity_fx": 0.10, "kr_bond": 0.20,
                "credit": 0.05, "global_duration": 0.20, "cash_mmf": 0.10,
            },
            rationale="t", bond_tips_share=0.5,
        ),
        conviction="high",
        dominant_scenario="goldilocks",
    )
    base.update(override)
    return ResearchDecision(**base)


def test_factor_scores_field_accepts_9_factor_dict():
    d = _minimal_research_decision(
        factor_scores={
            "F1_growth": 0.5, "F2_inflation": -0.3, "F3_real_rate": 0.1,
            "F4_term_premium": 0.0, "F5_credit_cycle": -0.2,
            "F6_krw_regime": 0.4, "F7_equity_vol_regime": 0.0,
            "F8_valuation": -0.5, "F9_market_dispersion": 0.2,
        }
    )
    assert d.factor_scores["F1_growth"] == 0.5
    assert len(d.factor_scores) == 9


def test_factor_contributions_field_accepts_attribution():
    d = _minimal_research_decision(
        factor_contributions={
            "F1_growth": {"kr_equity": 0.01, "global_equity": 0.02,
                          "fx_commodity": 0.0, "bond": -0.02, "cash_mmf": -0.01},
        }
    )
    assert d.factor_contributions["F1_growth"]["global_equity"] == 0.02


def test_baseline_bucket_field_accepts_dict():
    d = _minimal_research_decision(
        baseline_bucket={"kr_equity": 0.12, "global_equity": 0.20,
                         "fx_commodity": 0.15, "bond": 0.33, "cash_mmf": 0.20}
    )
    assert d.baseline_bucket["bond"] == 0.33


def test_safety_diagnostics_field_accepts_dict():
    d = _minimal_research_decision(
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
    d = _minimal_research_decision()
    assert d.factor_scores == {}
    assert d.factor_contributions == {}
    assert d.baseline_bucket == {}
    assert d.safety_diagnostics == {}


def test_extra_fields_ignored_for_archive_compat():
    """Pre-C5 archive 호환성 — 24-cell field 가 입력으로 들어와도 ignore."""
    d = _minimal_research_decision(
        # 가상의 legacy 24-cell field — extra="ignore" 로 silently dropped
        dominant_cell={"cycle": "A", "tail": "N", "kr": "F"},
        dominant_cell_probability=0.5,
        cycle_marginals={"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0},
    )
    # 새 schema 의 field 는 정상 동작
    assert d.dominant_scenario == "goldilocks"
    # 24-cell field 는 model 에 존재하지 않음
    assert not hasattr(d, "dominant_cell")
    assert not hasattr(d, "cycle_marginals")
