"""Debate sub-graphs (D2 hybrid topology).

Phase 1 변경: Bull/Bear adaptive-rounds 루프 폐기 → 단일 estimator 노드.
Sub-graph isolation은 유지 (parent에 raw 노이즈 안 새도록).
"""
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.researchers.debate_state import InvestDebateState
from tradingagents.agents.risk_mgmt.debate_state import RiskDebateState


def build_invest_debate_subgraph(estimator_node, **_kwargs):
    """Single-estimator sub-graph (Phase 1).

    기존 시그니처와의 호환: 추가 인자 (max_rounds_cap 등)는 무시하고 받음.
    구조:
        START → estimator → END
    estimator 노드는 ResearchDecision/BucketTarget/summary를 한 번에 산출.
    """
    sg = StateGraph(InvestDebateState)
    sg.add_node("estimator", estimator_node)
    sg.add_edge(START, "estimator")
    sg.add_edge("estimator", END)
    return sg.compile()


def build_risk_debate_subgraph(
    aggressive_node, conservative_node, neutral_node, judge_node,
    max_rounds: int = 1,
):
    """Build the 3-way risk debate sub-graph (D2 isolated).

    Sequence per round: aggressive → conservative → neutral.
    Neutral node increments round_count, then we either loop back or run judge.
    """
    sg = StateGraph(RiskDebateState)
    sg.add_node("aggressive", aggressive_node)
    sg.add_node("conservative", conservative_node)
    sg.add_node("neutral", neutral_node)
    sg.add_node("judge", judge_node)

    sg.add_edge(START, "aggressive")
    sg.add_edge("aggressive", "conservative")
    sg.add_edge("conservative", "neutral")

    def should_continue(state) -> str:
        if state["round_count"] >= state["max_rounds"]:
            return "judge"
        return "aggressive"

    sg.add_conditional_edges(
        "neutral", should_continue,
        {"aggressive": "aggressive", "judge": "judge"},
    )
    sg.add_edge("judge", END)

    return sg.compile()
