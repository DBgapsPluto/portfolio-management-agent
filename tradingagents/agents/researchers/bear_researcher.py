"""Bear researcher: argues for higher safe-asset weight (자산군 단위, 종목 X)."""
from langchain_core.messages import AIMessage

from tradingagents.schemas.research import ResearcherTurn
from tradingagents.skills._helpers import invoke_with_structured_retry


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

Output a ResearcherTurn JSON:
- argument: Korean, ≤400 chars. Cite 2-3 evidence points. Acknowledge ONE upside risk.
- confidence: how sure you are that your defensive stance is correct (0.0 = no idea, 1.0 = certain).
  Calibrate honestly — if evidence is mixed, drop below 0.6.
- proposed_risk_tilt: total risk-asset weight you'd recommend [0.0, 1.0]. Bear typically ≤0.45."""


def create_bear_researcher(quick_llm):
    def node(state):
        previous_bull = (
            state["bull_arguments"][-1].argument if state["bull_arguments"] else "(none)"
        )
        prompt = BEAR_PROMPT.format(
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            technical_summary=state["technical_summary"],
            news_summary=state["news_summary"],
            previous_bull=previous_bull,
        )
        turn: ResearcherTurn = invoke_with_structured_retry(
            quick_llm, ResearcherTurn,
            [{"role": "user", "content": prompt}],
            max_retries=1,
        )
        return {
            "bear_arguments": state["bear_arguments"] + [turn],
            "messages": state["messages"] + [
                AIMessage(content=f"[Bear r{state['round_count']}] {turn.argument}")
            ],
            "round_count": state["round_count"] + 1,
        }

    return node
