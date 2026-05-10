"""Bull researcher: argues for higher risk asset weight (자산군 단위, 종목 X)."""
from langchain_core.messages import AIMessage, HumanMessage


BULL_PROMPT = """\
You are the Bull researcher in an asset-allocation team. Your job is to argue
for higher risk-asset weight (KR/global equity, FX/commodity).

Cite SPECIFIC evidence from the analyst summaries below — never invent numbers.

Macro:
{macro_summary}

Risk:
{risk_summary}

Technical:
{technical_summary}

News:
{news_summary}

Previous Bear argument: {previous_bear}

In ≤400 chars (Korean):
1. State your proposed risk-asset bucket weight (% of 100, in 5% increments).
2. Cite 2-3 evidence points by quoting the specific data above.
3. Acknowledge ONE counter-risk."""


def create_bull_researcher(quick_llm):
    def node(state):
        previous_bear = state["bear_arguments"][-1] if state["bear_arguments"] else "(none)"
        prompt = BULL_PROMPT.format(
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            technical_summary=state["technical_summary"],
            news_summary=state["news_summary"],
            previous_bear=previous_bear,
        )
        response = quick_llm.invoke([HumanMessage(content=prompt)])
        argument = response.content[:400]
        return {
            "bull_arguments": state["bull_arguments"] + [argument],
            "messages": state["messages"] + [AIMessage(content=f"[Bull r{state['round_count']}] {argument}")],
        }

    return node
