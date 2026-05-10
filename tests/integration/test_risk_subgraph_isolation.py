"""D2 — risk debate sub-graph isolation."""
from langchain_core.messages import HumanMessage

from tradingagents.agents.risk_mgmt.debate_state import RiskDebateState
from tradingagents.graph.debate_subgraph import build_risk_debate_subgraph


def test_risk_subgraph_runs_one_round():
    def fake_aggressive(state):
        return {
            "aggressive_arguments": state.get("aggressive_arguments", []) + ["agg"],
            "messages": state["messages"] + [HumanMessage(content="AGG_RAW")],
        }

    def fake_conservative(state):
        return {
            "conservative_arguments": state.get("conservative_arguments", []) + ["cons"],
            "messages": state["messages"] + [HumanMessage(content="CONS_RAW")],
        }

    def fake_neutral(state):
        return {
            "neutral_arguments": state.get("neutral_arguments", []) + ["neut"],
            "messages": state["messages"] + [HumanMessage(content="NEUT_RAW")],
            "round_count": state["round_count"] + 1,
        }

    def fake_judge(state):
        return {
            "weight_adjustment": {"delta": {"A1": -0.03}, "reasoning": "x"},
            "risk_debate_summary": "## Risk Debate Outcome\n...",
        }

    sg = build_risk_debate_subgraph(
        fake_aggressive, fake_conservative, fake_neutral, fake_judge,
        max_rounds=1,
    )

    sub_input = RiskDebateState(
        messages=[],
        weight_vector_input=None,
        correlation_clusters_summary="",
        macro_summary="m", risk_summary="r",
        aggressive_arguments=[], conservative_arguments=[], neutral_arguments=[],
        round_count=0, max_rounds=1,
        weight_adjustment=None,
        risk_debate_summary="",
    )
    result = sg.invoke(sub_input)
    assert result["round_count"] == 1
    assert "weight_adjustment" in result
    assert result["weight_adjustment"]["delta"] == {"A1": -0.03}
    assert "Risk Debate Outcome" in result["risk_debate_summary"]
