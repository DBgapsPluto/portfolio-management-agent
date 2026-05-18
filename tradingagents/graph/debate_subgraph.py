"""Debate sub-graphs (D2 hybrid topology).

Phase 1 (Stage 2 재설계): Bull/Bear adaptive-rounds 루프 폐기 → 단일 estimator.
Stage 4 Phase 1: Aggressive/Conservative/Neutral 토론 폐기 → RiskOverlay 단일 judge.
"""
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.researchers.debate_state import InvestDebateState


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


