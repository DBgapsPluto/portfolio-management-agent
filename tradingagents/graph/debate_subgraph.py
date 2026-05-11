"""Debate sub-graphs (D2 hybrid topology).

Bull/Bear and Risk debate clusters use isolated MessagesState subclasses so
raw debate messages don't leak to the parent AgentState. Parent receives
only structured judge output + summary str.
"""
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.researchers.debate_state import InvestDebateState
from tradingagents.agents.risk_mgmt.debate_state import RiskDebateState


_CONF_STOP_THRESHOLD = 0.75  # both sides confident enough → judge
_DIVERGENCE_STOP_THRESHOLD = 0.15  # proposed_risk_tilt gap small → convergence reached


def build_invest_debate_subgraph(
    bull_node, bear_node, judge_node, max_rounds_cap: int = 3,
):
    """Sub-graph that loops Bull→Bear adaptively, then runs judge.

    Adaptive stop conditions (each evaluated after every Bull→Bear round):
      1. round_count >= max_rounds_cap (hard safety net, default 3)
      2. avg(confidence_bull, confidence_bear) >= 0.75
         (both sides confident — judging now is robust)
      3. |bull.proposed_risk_tilt − bear.proposed_risk_tilt| <= 0.15
         (sides converged — debate plateaued)

    Otherwise, run another Bull→Bear round.
    Returns a compiled sub-graph.
    """
    sg = StateGraph(InvestDebateState)
    sg.add_node("bull", bull_node)
    sg.add_node("bear", bear_node)
    sg.add_node("judge", judge_node)

    sg.add_edge(START, "bull")
    sg.add_edge("bull", "bear")

    def should_continue(state) -> str:
        # bear node increments round_count, so this runs after a complete round
        if state["round_count"] >= state["max_rounds_cap"]:
            return "judge"
        bull_last = state["bull_arguments"][-1]
        bear_last = state["bear_arguments"][-1]
        avg_conf = (bull_last.confidence + bear_last.confidence) / 2
        if avg_conf >= _CONF_STOP_THRESHOLD:
            return "judge"
        divergence = abs(bull_last.proposed_risk_tilt - bear_last.proposed_risk_tilt)
        if divergence <= _DIVERGENCE_STOP_THRESHOLD:
            return "judge"
        return "bull"

    sg.add_conditional_edges("bear", should_continue, {"bull": "bull", "judge": "judge"})
    sg.add_edge("judge", END)

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
