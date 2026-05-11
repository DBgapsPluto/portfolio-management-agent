"""D2 — raw debate messages must NOT leak to parent state."""
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.researchers.debate_state import InvestDebateState
from tradingagents.agents.utils.agent_states import AgentState, _create_empty_state
from tradingagents.graph.debate_subgraph import build_invest_debate_subgraph
from tradingagents.schemas.research import ResearcherTurn


def _bull_turn(conf=0.9, tilt=0.65):
    return ResearcherTurn(argument="bull says X", confidence=conf, proposed_risk_tilt=tilt)


def _bear_turn(conf=0.9, tilt=0.55):
    return ResearcherTurn(argument="bear says Y", confidence=conf, proposed_risk_tilt=tilt)


def test_subgraph_messages_isolated():
    def fake_bull(state):
        return {
            "bull_arguments": state.get("bull_arguments", []) + [_bull_turn()],
            "messages": state["messages"] + [HumanMessage(content="BULL_RAW")],
        }

    def fake_bear(state):
        return {
            "bear_arguments": state.get("bear_arguments", []) + [_bear_turn()],
            "messages": state["messages"] + [HumanMessage(content="BEAR_RAW")],
            "round_count": state["round_count"] + 1,
        }

    def fake_judge(state):
        return {
            "bucket_target": None,
            "research_debate_summary": "summary handoff: 60/40",
        }

    # conf=0.9 each → avg 0.9 ≥ 0.75 → stops after round 1 (regardless of cap)
    sg = build_invest_debate_subgraph(fake_bull, fake_bear, fake_judge, max_rounds_cap=3)

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
            messages=[],  # FRESH — not state["messages"]
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            technical_summary=state["technical_summary"],
            news_summary=state["news_summary"],
            bull_arguments=[], bear_arguments=[],
            round_count=0, max_rounds_cap=3,
            bucket_target=None,
            research_debate_summary="",
        )
        sub_result = sg.invoke(sub_input)
        # Return ONLY the summary to parent — drop raw msgs
        return {"research_debate_summary": sub_result["research_debate_summary"]}

    main_sg = StateGraph(AgentState)
    main_sg.add_node("debate", parent_invoke)
    main_sg.add_edge(START, "debate")
    main_sg.add_edge("debate", END)
    graph = main_sg.compile()

    final = graph.invoke(parent)
    # Parent state messages should be EMPTY (sub-graph msgs isolated)
    assert "BULL_RAW" not in str(final["messages"])
    assert "BEAR_RAW" not in str(final["messages"])
    assert "60/40" in final["research_debate_summary"]
