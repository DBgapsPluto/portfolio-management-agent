from unittest.mock import MagicMock

from tradingagents.agents.managers.risk_judge import (
    create_risk_judge, WeightAdjustment,
)
from tradingagents.agents.risk_mgmt.aggressive_debator import create_aggressive_debator
from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator
from tradingagents.agents.risk_mgmt.neutral_debator import create_neutral_debator
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector


def _state():
    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A1": 0.3, "A2": 0.4, "A3": 0.3},
        rationale="x",
    )
    return {
        "messages": [],
        "weight_vector_input": wv,
        "correlation_clusters_summary": "AI cluster: 3 tickers",
        "macro_summary": "regime: recession",
        "risk_summary": "VIX 28",
        "aggressive_arguments": [], "conservative_arguments": [], "neutral_arguments": [],
        "round_count": 0,
    }


def test_aggressive_debator_appends():
    quick_llm = MagicMock()
    quick_llm.invoke.return_value.content = "위험자산 65% 집중 주장."
    node = create_aggressive_debator(quick_llm)
    result = node(_state())
    assert len(result["aggressive_arguments"]) == 1


def test_conservative_debator_appends():
    quick_llm = MagicMock()
    quick_llm.invoke.return_value.content = "AI 쏠림 위험 — cluster cap 25% 적용."
    node = create_conservative_debator(quick_llm)
    result = node(_state())
    assert len(result["conservative_arguments"]) == 1


def test_neutral_debator_increments_round():
    quick_llm = MagicMock()
    quick_llm.invoke.return_value.content = "중간 — A2를 -3%p, A3를 +3%p."
    node = create_neutral_debator(quick_llm)
    state = _state()
    state["aggressive_arguments"] = ["agg"]
    state["conservative_arguments"] = ["cons"]
    result = node(state)
    assert len(result["neutral_arguments"]) == 1
    assert result["round_count"] == 1


def test_risk_judge_returns_adjustment():
    deep_llm = MagicMock()
    out = WeightAdjustment(
        delta={"A1": -0.03, "A3": 0.03},
        reasoning="reduce A1 single risk, increase A3 diversification",
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = out

    node = create_risk_judge(deep_llm)
    state = _state()
    state["aggressive_arguments"] = ["agg"]
    state["conservative_arguments"] = ["cons"]
    state["neutral_arguments"] = ["neut"]
    result = node(state)
    assert "weight_adjustment" in result
    assert "delta" in result["weight_adjustment"]
    assert "risk_debate_summary" in result
