"""Bear researcher: argues for higher safe-asset weight (자산군 단위, 종목 X)."""
from langchain_core.messages import AIMessage, HumanMessage


BEAR_PROMPT = """\
You are the Bear researcher in an asset-allocation team. Your job is to argue
for higher safe-asset weight (bonds, MMF, gold).

Cite SPECIFIC evidence from the analyst summaries below — never invent numbers.

Macro:
{macro_summary}

Risk:
{risk_summary}

Technical:
{technical_summary}

News:
{news_summary}

Previous Bull argument: {previous_bull}

In ≤400 chars (Korean):
1. State your proposed safe-asset bucket weight (% of 100, in 5% increments).
2. Cite 2-3 evidence points by quoting the specific data above.
3. Acknowledge ONE upside risk to your defensive view."""


def create_bear_researcher(quick_llm):
    def node(state):
        previous_bull = state["bull_arguments"][-1] if state["bull_arguments"] else "(none)"
        prompt = BEAR_PROMPT.format(
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            technical_summary=state["technical_summary"],
            news_summary=state["news_summary"],
            previous_bull=previous_bull,
        )
        response = quick_llm.invoke([HumanMessage(content=prompt)])
        argument = response.content[:400]
        return {
            "bear_arguments": state["bear_arguments"] + [argument],
            "messages": state["messages"] + [AIMessage(content=f"[Bear r{state['round_count']}] {argument}")],
            "round_count": state["round_count"] + 1,
        }

    return node
