"""Aggressive debator: pushes for higher conviction / faster turnover."""
from langchain_core.messages import AIMessage, HumanMessage


AGGRESSIVE_PROMPT = """\
You are the Aggressive risk debator. Push for HIGHER conviction.

Weight vector proposed by Allocator: {weights_summary}
Macro: {macro_summary}
Risk: {risk_summary}
Clusters: {clusters_summary}

In ≤300 chars (Korean):
1. Argue for concentration on highest-momentum bets (risk-on tilt).
2. Cite turnover floor compliance (대회 §3.1: ≥80% initial).
3. Critique current weights as too defensive."""


def create_aggressive_debator(quick_llm):
    def node(state):
        wv = state.get("weight_vector_input")
        weights_summary = (
            f"top weights: {sorted(wv.weights.items(), key=lambda x: -x[1])[:3]}"
            if wv else "(none)"
        )
        prompt = AGGRESSIVE_PROMPT.format(
            weights_summary=weights_summary,
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            clusters_summary=state["correlation_clusters_summary"],
        )
        response = quick_llm.invoke([HumanMessage(content=prompt)])
        argument = response.content[:300]
        return {
            "aggressive_arguments": state["aggressive_arguments"] + [argument],
            "messages": state["messages"] + [AIMessage(content=f"[Aggressive r{state['round_count']}] {argument}")],
        }

    return node
