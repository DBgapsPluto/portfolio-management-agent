"""3 lens debator — deterministic threshold + preset overlay."""
from types import SimpleNamespace

import pytest

from tradingagents.agents.risk_lens.concentration_lens import run_concentration_lens
from tradingagents.agents.risk_lens.macro_conditional_lens import run_macro_conditional_lens
from tradingagents.agents.risk_lens.tail_risk_lens import run_tail_risk_lens
from tradingagents.schemas.portfolio import (
    CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.skills.risk.portfolio_metrics import PortfolioNumerics


# ===== tail_risk_lens =====

def _numerics(cvar=0.02, hhi=0.10, top1=0.15, top3=0.40, max_cluster=0.20):
    return PortfolioNumerics(
        hhi=hhi, top1_weight=top1, top3_weight_sum=top3,
        cluster_exposure={"c1": max_cluster, "c2": max_cluster - 0.10},
        max_cluster_exposure=max_cluster,
        realized_vol_60d=0.01,
        var_95_1d=cvar * 0.8, cvar_95_1d=cvar,
        n_assets=10,
    )


def test_tail_risk_critical_cvar():
    c = run_tail_risk_lens(_numerics(cvar=0.045), systemic_score=5.0)
    assert c.level == "critical"
    assert c.proposed_overlay.risk_asset_multiplier == 0.6


def test_tail_risk_critical_systemic_only():
    c = run_tail_risk_lens(_numerics(cvar=0.01), systemic_score=9.5)
    assert c.level == "critical"


def test_tail_risk_critical_both_panic_signals():
    c = run_tail_risk_lens(
        _numerics(cvar=0.02), systemic_score=6.0,
        vix_term_regime="backwardation", funding_regime="stress",
    )
    assert c.level == "critical"


def test_tail_risk_high():
    c = run_tail_risk_lens(_numerics(cvar=0.032), systemic_score=5.0)
    assert c.level == "high"
    assert c.proposed_overlay.risk_asset_multiplier == 0.75


def test_tail_risk_medium():
    c = run_tail_risk_lens(_numerics(cvar=0.026), systemic_score=5.0)
    assert c.level == "medium"


def test_tail_risk_none_for_calm():
    c = run_tail_risk_lens(_numerics(cvar=0.015), systemic_score=4.0)
    assert c.level == "none"
    assert c.proposed_overlay.risk_asset_multiplier == 1.0


# ===== concentration_lens =====

def _wv_uniform(n=10):
    return WeightVector(
        method=OptimizationMethod.HRP,
        weights={f"A{i:03d}": 1.0 / n for i in range(1, n + 1)},
        rationale="t",
    )


def test_concentration_critical_hhi():
    n = _numerics(hhi=0.25, top1=0.21)
    c = run_concentration_lens(n, _wv_uniform())
    assert c.level == "critical"


def test_concentration_high_cluster():
    n = _numerics(hhi=0.10, max_cluster=0.45)
    c = run_concentration_lens(n, _wv_uniform())
    assert c.level == "high"


def test_concentration_medium():
    n = _numerics(hhi=0.13, max_cluster=0.20)
    c = run_concentration_lens(n, _wv_uniform())
    assert c.level == "medium"


def test_concentration_none_for_diversified():
    n = _numerics(hhi=0.08, max_cluster=0.20, top1=0.10, top3=0.30)
    c = run_concentration_lens(n, _wv_uniform(20))
    assert c.level == "none"


def test_concentration_cluster_caps_strict_only_vs_validator_baseline():
    """Stage 5 정리 ⑥ — validator baseline 0.25 hard 대비 strict한 cap만 제안.

    Validator cluster_cap = 0.25 (hard).
    Stage 4 concentration_lens는 critical=0.18, high=0.22로 strict only.
    medium은 cluster_caps 빈 dict (validator baseline 0.25로 충분).
    """
    # critical
    crit = run_concentration_lens(
        _numerics(hhi=0.25), _wv_uniform(),
    )
    assert crit.level == "critical"
    if crit.proposed_overlay.cluster_caps:
        for cap_value in crit.proposed_overlay.cluster_caps.values():
            assert cap_value < 0.25, f"critical cap {cap_value} not strict vs 0.25"

    # high
    high = run_concentration_lens(
        _numerics(hhi=0.10, max_cluster=0.45), _wv_uniform(),
    )
    assert high.level == "high"
    if high.proposed_overlay.cluster_caps:
        for cap_value in high.proposed_overlay.cluster_caps.values():
            assert cap_value < 0.25, f"high cap {cap_value} not strict vs 0.25"

    # medium — validator baseline 0.25로 충분하므로 빈 cluster_caps
    med = run_concentration_lens(
        _numerics(hhi=0.13, max_cluster=0.20), _wv_uniform(),
    )
    assert med.level == "medium"
    assert med.proposed_overlay.cluster_caps == {}


# ===== macro_conditional_lens =====

def _candidates():
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A001", "A002"],
            "global_equity": ["A003", "A004"],
            "fx_commodity": ["A005"],
            "bond": ["A006", "A007"],
            "cash_mmf": ["A008"],
        },
        selection_criteria="t", total_candidates=8,
    )


def _wv_risk(risk_weight: float) -> WeightVector:
    """위험자산(A001-A005) 비중 risk_weight, 나머지는 안전자산."""
    safe = 1.0 - risk_weight
    per_risk = risk_weight / 5  # 5 risk tickers
    per_safe = safe / 3         # 3 safe tickers
    return WeightVector(
        method=OptimizationMethod.HRP,
        weights={
            "A001": per_risk, "A002": per_risk, "A003": per_risk,
            "A004": per_risk, "A005": per_risk,
            "A006": per_safe, "A007": per_safe, "A008": per_safe,
        },
        rationale="t",
    )


def _decision(scenario, conviction="medium"):
    return SimpleNamespace(dominant_scenario=scenario, conviction=conviction)


def test_macro_critical_global_credit_with_risk_assets():
    c = run_macro_conditional_lens(
        _wv_risk(0.50), _candidates(),
        research_decision=_decision("global_credit"),
        systemic_score=7.0,
    )
    assert c.level == "critical"


def test_macro_high_recession_with_high_risk():
    c = run_macro_conditional_lens(
        _wv_risk(0.55), _candidates(),
        research_decision=_decision("broad_recession"),
        systemic_score=8.0,
    )
    assert c.level == "high"


def test_macro_low_conviction_with_aggressive_weight():
    c = run_macro_conditional_lens(
        _wv_risk(0.70), _candidates(),
        research_decision=_decision("goldilocks", conviction="low"),
        systemic_score=5.0,
    )
    assert c.level == "medium"


def test_macro_none_for_aligned_scenario():
    c = run_macro_conditional_lens(
        _wv_risk(0.65), _candidates(),
        research_decision=_decision("goldilocks", conviction="high"),
        systemic_score=4.0,
    )
    assert c.level == "none"


def test_macro_lens_recession_high_branch_reachable():
    """recession 분기에서 risk_weight=0.70 → high (이전엔 medium에서 fall-through)."""
    from tradingagents.agents.risk_lens.macro_conditional_lens import (
        run_macro_conditional_lens,
    )
    from tradingagents.schemas.portfolio import (
        CandidateSet, OptimizationMethod, WeightVector,
    )

    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={"A001": 0.20, "A002": 0.20, "A003": 0.20, "A004": 0.20, "A005": 0.20},
        rationale="test",
    )
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A001"], "global_equity": ["A002"],
            "fx_commodity": ["A003"], "bond": ["A004"], "cash_mmf": ["A005"],
        },
        selection_criteria="test", total_candidates=5,
    )
    # risk_weight 0.75 만들기: 위험자산 3개 합쳐 0.75
    wv2 = wv.model_copy(update={
        "weights": {"A001": 0.25, "A002": 0.25, "A003": 0.25, "A004": 0.15, "A005": 0.10},
    })
    result = run_macro_conditional_lens(
        wv2, cs, research_decision=None, systemic_score=5.0,
        regime_quadrant="recession_disinflation",
    )
    assert result.level == "high", f"expected high, got {result.level}"


def test_macro_lens_recession_medium_still_works():
    """recession + risk=0.60 → medium (high 분기 추가 후에도 medium 정상)."""
    from tradingagents.agents.risk_lens.macro_conditional_lens import (
        run_macro_conditional_lens,
    )
    from tradingagents.schemas.portfolio import (
        CandidateSet, OptimizationMethod, WeightVector,
    )

    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={"A001": 0.20, "A002": 0.20, "A003": 0.20, "A004": 0.20, "A005": 0.20},
        rationale="test",
    )
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A001"], "global_equity": ["A002"],
            "fx_commodity": ["A003"], "bond": ["A004"], "cash_mmf": ["A005"],
        },
        selection_criteria="test", total_candidates=5,
    )
    # risk_weight=0.60 (각 위험자산 0.20)
    result = run_macro_conditional_lens(
        wv, cs, research_decision=None, systemic_score=5.0,
        regime_quadrant="recession_inflation",
    )
    assert result.level == "medium", f"expected medium, got {result.level}"
