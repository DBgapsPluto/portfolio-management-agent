"""risk_judge 가 apply_overlay_to_weights outcome 을 RiskOverlay 에 기록."""
from unittest.mock import patch

import numpy as np
import pandas as pd

from tradingagents.agents.managers.risk_judge import create_risk_judge
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay


def _state():
    tickers = [f"A{i:03d}" for i in range(1, 11)]
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    returns = pd.DataFrame(
        {t: rng.normal(0.0005, 0.005, 300) for t in tickers}, index=idx,
    )

    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in tickers}, rationale="1st",
    )
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity":             tickers[0:2],
            "global_equity":         tickers[2:4],
            "cyclical_commodity_fx": tickers[4:6],
            "kr_bond":               tickers[6:8],
            "cash_mmf":              tickers[8:10],
        },
        selection_criteria="test", total_candidates=10,
    )
    bt = BucketTarget(
        weights={
            "kr_equity":             0.20,
            "global_equity":         0.20,
            "precious_metals":       0.00,
            "cyclical_commodity_fx": 0.20,
            "kr_bond":               0.20,
            "credit":                0.00,
            "global_duration":       0.00,
            "cash_mmf":              0.20,
        },
        rationale="test",
    )
    return {
        "as_of_date": "2024-06-15",
        "weight_vector":     wv,
        "candidate_set":     cs,
        "bucket_target":     bt,
        "risk_report":       None,
        "macro_report":      None,
        "research_decision": None,
        "technical_report":  None,
    }, returns


def test_risk_judge_records_overlay_outcome_in_overlay_schema():
    """risk_judge 노드가 apply_overlay_to_weights 의 outcome 을 RiskOverlay 에 기록.

    apply_overlay_to_weights 를 mock 해서 weight_changed=True 를 반환하게 강제.
    risk_judge 는 weight_changed=True → outcome="weights_shrunk" 로 파생.
    """
    state, returns = _state()
    node = create_risk_judge()

    with patch(
        "tradingagents.agents.managers.risk_judge.fetch_returns_matrix",
        return_value=returns,
    ):
        # apply_overlay_to_weights 는 risk_judge 함수 내부에서 lazy import 됨.
        # 해당 함수의 원본 모듈을 patch. weight_changed=True → outcome="weights_shrunk"
        with patch(
            "tradingagents.agents.allocator.overlay_apply.apply_overlay_to_weights",
            return_value=(state["weight_vector"], True),
        ), patch(
            # ~/.tradingagents/stats/overlay_outcomes.jsonl 폴루션 차단
            "tradingagents.agents.managers.risk_judge.record_overlay_outcome",
            lambda **kw: None,
        ):
            out = node(state)

    overlay = out["risk_overlay"]
    assert isinstance(overlay, RiskOverlay)
    assert overlay.overlay_apply_outcome == "weights_shrunk", (
        f"expected weights_shrunk, got {overlay.overlay_apply_outcome}"
    )


def test_risk_judge_skip_when_inputs_missing_sets_primary_success():
    """input 누락 시 RiskOverlay.no_concerns() → outcome=primary_success default."""
    node = create_risk_judge()
    out = node({"as_of_date": "2024-06-15"})  # weight_vector etc. 없음
    assert out["risk_overlay"].overlay_apply_outcome == "primary_success"


# ---------- Stage 4 audit (2026-05-26) tests ----------


def test_degraded_risk_signals_skip_lens():
    """Stage 4 audit Task 0: risk_report 의 systemic/vix/funding 모두 sentinel
    이면 lens 호출 skip + empty overlay + risk_judge_attribution['skipped']
    = 'risk_signals_degraded'.
    """
    from types import SimpleNamespace

    state, returns = _state()
    # risk_report 를 sentinel snapshot 으로 강제. staleness=99 마킹.
    state["risk_report"] = SimpleNamespace(
        systemic_score=SimpleNamespace(score=5.0, staleness_days=99),
        vix_term=SimpleNamespace(regime="contango", staleness_days=99),
        funding_stress=SimpleNamespace(regime="calm", staleness_days=99),
    )
    node = create_risk_judge()

    with patch(
        "tradingagents.agents.managers.risk_judge.fetch_returns_matrix",
        return_value=returns,
    ), patch(
        "tradingagents.agents.managers.risk_judge.record_overlay_outcome",
        lambda **kw: None,
    ):
        out = node(state)

    overlay = out["risk_overlay"]
    # empty overlay (lens skip) — strength_applied = 0
    assert overlay.strength_applied == 0.0
    # attribution 가시화
    rj_attr = out.get("risk_judge_attribution", {})
    assert rj_attr.get("skipped") == "risk_signals_degraded"
    assert rj_attr["risk_signal_staleness"]["systemic"] == 99
    assert rj_attr["risk_signal_staleness"]["vix_term"] == 99
    assert rj_attr["risk_signal_staleness"]["funding"] == 99
    # Stage 3 weight_vector 그대로 보존
    assert out["weight_vector"].weights == state["weight_vector"].weights


def test_risk_judge_attribution_threads_lens_concerns():
    """Stage 4 audit Task 1: risk_judge_attribution 에 lens_concerns,
    strength_applied, severity_decision 가 모두 기록.
    """
    state, returns = _state()
    node = create_risk_judge()

    with patch(
        "tradingagents.agents.managers.risk_judge.fetch_returns_matrix",
        return_value=returns,
    ), patch(
        "tradingagents.agents.managers.risk_judge.record_overlay_outcome",
        lambda **kw: None,
    ):
        out = node(state)

    rj_attr = out.get("risk_judge_attribution", {})
    # lens_concerns: 3 lens 항목 (tail_risk, concentration, macro_conditional)
    assert "lens_concerns" in rj_attr
    assert len(rj_attr["lens_concerns"]) == 3
    lenses = {c["lens"] for c in rj_attr["lens_concerns"]}
    assert lenses == {"tail_risk", "concentration", "macro_conditional"}
    # strength + decision
    assert "strength_applied" in rj_attr
    assert "severity_decision" in rj_attr
    assert "multiplier" in rj_attr
    # input_present 가 모두 채워짐
    assert rj_attr["input_present"]["weight_vector"] is True
    assert rj_attr["input_present"]["candidate_set"] is True


def test_named_const_present_in_lenses():
    """Stage 4 audit Task 2/3/4: 각 lens + aggregator + metrics 의 const 존재."""
    from tradingagents.agents.risk_lens import (
        concentration_lens as cl,
        macro_conditional_lens as mcl,
        tail_risk_lens as trl,
    )
    from tradingagents.skills.risk import (
        portfolio_metrics as pm, severity_aggregator as sa,
    )

    # tail_risk_lens
    assert trl.CRITICAL_CVAR == 0.04
    assert trl.MULTIPLIER_CRITICAL == 0.6

    # concentration_lens
    assert cl.CRITICAL_HHI == 0.20
    assert cl.CRITICAL_CLUSTER_CAP == 0.18

    # macro_conditional_lens
    assert mcl.GLOBAL_CREDIT_CRITICAL == 0.30
    assert mcl.MULTIPLIER_CRITICAL == 0.65

    # severity_aggregator
    assert sa.STRENGTH_CRITICAL_TWO_PLUS == 1.0
    assert sa.STRENGTH_CRITICAL_ONE == 0.7

    # portfolio_metrics
    assert pm.MIN_OBS_REALIZED_VOL == 60
    assert pm.MIN_OBS_CVAR == 100
    assert pm.VAR_PERCENTILE == 95.0
