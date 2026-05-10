"""Conservative debator: pushes for lower conviction / single-risk control."""
from langchain_core.messages import AIMessage, HumanMessage


CONSERVATIVE_PROMPT = """\
You are the Conservative risk debator. Argue for LOWER conviction & single-risk control.

Weight vector proposed by Allocator: {weights_summary}
Macro: {macro_summary}
Risk: {risk_summary}
Clusters: {clusters_summary}

In ≤300 chars (Korean):
1. Identify single-risk concentration (e.g., AI 쏠림) by quoting cluster summary.
2. Argue for cluster-level cap (단일 클러스터 ≤25%).
3. Critique aggressive bets given current macro risk."""


def create_conservative_debator(quick_llm):
    def node(state):
        wv = state.get("weight_vector_input")
        weights_summary = (
            f"top weights: {sorted(wv.weights.items(), key=lambda x: -x[1])[:3]}"
            if wv else "(none)"
        )
        prompt = CONSERVATIVE_PROMPT.format(
            weights_summary=weights_summary,
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            clusters_summary=state["correlation_clusters_summary"],
        )
        response = quick_llm.invoke([HumanMessage(content=prompt)])
        argument = response.content[:300]
        return {
            "conservative_arguments": state["conservative_arguments"] + [argument],
            "messages": state["messages"] + [AIMessage(content=f"[Conservative r{state['round_count']}] {argument}")],
        }

    return node
