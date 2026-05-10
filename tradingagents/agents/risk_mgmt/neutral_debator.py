"""Neutral debator: mediates Aggressive vs Conservative."""
from langchain_core.messages import AIMessage, HumanMessage


NEUTRAL_PROMPT = """\
You are the Neutral mediator in the risk debate.

Aggressive's last argument: {aggressive_last}
Conservative's last argument: {conservative_last}

In ≤300 chars (Korean):
1. Identify the substantive disagreement.
2. Propose a balanced weight tilt (small +/-5%p adjustment).
3. NO new evidence — only synthesize the two sides."""


def create_neutral_debator(quick_llm):
    def node(state):
        agg = state["aggressive_arguments"][-1] if state["aggressive_arguments"] else "(none)"
        cons = state["conservative_arguments"][-1] if state["conservative_arguments"] else "(none)"
        prompt = NEUTRAL_PROMPT.format(
            aggressive_last=agg,
            conservative_last=cons,
        )
        response = quick_llm.invoke([HumanMessage(content=prompt)])
        argument = response.content[:300]
        return {
            "neutral_arguments": state["neutral_arguments"] + [argument],
            "messages": state["messages"] + [AIMessage(content=f"[Neutral r{state['round_count']}] {argument}")],
            "round_count": state["round_count"] + 1,  # last debater increments
        }

    return node
