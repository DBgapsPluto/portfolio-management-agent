"""D2 — Stage 2 sub-graph의 raw 산출물이 parent state로 새지 않는지 검증.

Phase 1: Bull/Bear 토론 폐기 → 단일 estimator. 그래도 sub-graph isolation은 유지.
"""
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.researchers.debate_state import InvestDebateState
from tradingagents.agents.utils.agent_states import AgentState, _create_empty_state
from tradingagents.graph.debate_subgraph import build_invest_debate_subgraph


def test_subgraph_messages_isolated():
    """Estimator 노드가 messages를 만들어도 parent state로 안 새어나가야 함."""

    def fake_estimator(state):
        return {
            "bucket_target": None,
            "research_decision": None,
            "research_debate_summary": "summary handoff: dominant=goldilocks",
            "messages": state["messages"] + [HumanMessage(content="ESTIMATOR_RAW")],
        }

    sg = build_invest_debate_subgraph(fake_estimator)

    parent = _create_empty_state(
        as_of_date="2026-05-10", universe_path="x",
        capital_krw=100, preset_name="db_gaps",
    )
    parent["macro_summary"] = "macro test"
    parent["risk_summary"] = "risk test"
    parent["technical_summary"] = ""
    parent["news_summary"] = ""

    def parent_invoke(state):
        sub_input = InvestDebateState(
            messages=[],
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            technical_summary=state["technical_summary"],
            news_summary=state["news_summary"],
            bucket_target=None,
            research_decision=None,
            research_debate_summary="",
        )
        sub_result = sg.invoke(sub_input)
        return {"research_debate_summary": sub_result["research_debate_summary"]}

    main_sg = StateGraph(AgentState)
    main_sg.add_node("debate", parent_invoke)
    main_sg.add_edge(START, "debate")
    main_sg.add_edge("debate", END)
    graph = main_sg.compile()

    final = graph.invoke(parent)
    assert "ESTIMATOR_RAW" not in str(final["messages"])
    assert "goldilocks" in final["research_debate_summary"]
