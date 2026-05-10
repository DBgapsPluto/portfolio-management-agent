"""Debate sub-graphs (D2 hybrid topology).

Bull/Bear and Risk debate clusters use isolated MessagesState subclasses so
raw debate messages don't leak to the parent AgentState. Parent receives
only structured judge output + summary str.
"""
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.researchers.debate_state import InvestDebateState


def build_invest_debate_subgraph(
    bull_node, bear_node, judge_node, max_rounds: int = 1,
):
    """Sub-graph that loops Bull→Bear `max_rounds` times then runs judge.

    Returns a compiled sub-graph. Parent invokes via .invoke() with
    relevant summaries; the sub-graph returns BucketTarget + summary str.
    """
    sg = StateGraph(InvestDebateState)
    sg.add_node("bull", bull_node)
    sg.add_node("bear", bear_node)
    sg.add_node("judge", judge_node)

    sg.add_edge(START, "bull")
    sg.add_edge("bull", "bear")

    def should_continue(state) -> str:
        # bear node increments round_count, so check after bear runs
        if state["round_count"] >= state["max_rounds"]:
            return "judge"
        return "bull"

    sg.add_conditional_edges("bear", should_continue, {"bull": "bull", "judge": "judge"})
    sg.add_edge("judge", END)

    return sg.compile()
