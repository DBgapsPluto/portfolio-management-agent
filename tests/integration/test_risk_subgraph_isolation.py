"""Stage 4 Phase 1 — RiskOverlay no-op placeholder 검증.

기존 3-way advocacy debate sub-graph 폐기 (Aggressive/Conservative/Neutral).
Phase 1에서는 risk_judge가 항상 empty overlay 반환 (Phase 2에서 lens-based로 교체).

테스트 인프라 wiring:
  - state["risk_overlay"] 채워짐
  - empty overlay이면 weight_vector 변경 없음
  - risk_debate_summary에 placeholder 메시지
"""
from datetime import date

from tradingagents.agents.managers.risk_judge import create_risk_judge
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)


def _state_fixture():
    bucket = BucketTarget(
        kr_equity=0.20, global_equity=0.30, fx_commodity=0.10,
        bond=0.30, cash_mmf=0.10,
        rationale="test",
    )
    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A001": 0.20, "A002": 0.30, "A003": 0.10, "A004": 0.30, "A005": 0.10},
        rationale="Stage 3 1st result",
    )
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A001"], "global_equity": ["A002"],
            "fx_commodity": ["A003"], "bond": ["A004"], "cash_mmf": ["A005"],
        },
        selection_criteria="test", total_candidates=5,
    )
    return {
        "as_of_date": "2026-05-18",
        "macro_summary": "macro test", "risk_summary": "risk test",
        "technical_summary": "tech test", "news_summary": "news test",
        "weight_vector": wv,
        "candidate_set": cs,
        "bucket_target": bucket,
    }


def test_risk_judge_returns_empty_overlay_phase_1():
    """Phase 1: 항상 empty overlay 반환, weight_vector 변경 없음."""
    node = create_risk_judge(quick_llm=None, deep_llm=None)
    out = node(_state_fixture())

    overlay = out["risk_overlay"]
    assert overlay is not None
    assert overlay.is_empty()
    assert overlay.strength_applied == 0.0
    assert "weight_vector" not in out
    assert "Phase 1 placeholder" in out["risk_debate_summary"]


def test_risk_judge_handles_missing_state_gracefully():
    node = create_risk_judge()
    out = node({"as_of_date": "2026-05-18"})
    assert out["risk_overlay"].is_empty()
    assert "weight_vector" not in out
