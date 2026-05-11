"""Bull researcher: argues for higher risk asset weight (자산군 단위, 종목 X)."""
from langchain_core.messages import AIMessage

from tradingagents.schemas.research import ResearcherTurn
from tradingagents.skills._helpers import invoke_with_structured_retry


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

Output a ResearcherTurn JSON:
- argument: Korean, ≤400 chars. Cite 2-3 evidence points. Acknowledge ONE counter-risk.
- confidence: how sure you are that your bullish stance is correct (0.0 = no idea, 1.0 = certain).
  Calibrate honestly — if evidence is mixed, drop below 0.6.
- proposed_risk_tilt: total risk-asset weight you'd recommend [0.0, 1.0]. Bull typically ≥0.55."""


def create_bull_researcher(quick_llm):
    def node(state):
        previous_bear = (
            state["bear_arguments"][-1].argument if state["bear_arguments"] else "(none)"
        )
        prompt = BULL_PROMPT.format(
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            technical_summary=state["technical_summary"],
            news_summary=state["news_summary"],
            previous_bear=previous_bear,
        )
        turn: ResearcherTurn = invoke_with_structured_retry(
            quick_llm, ResearcherTurn,
            [{"role": "user", "content": prompt}],
            max_retries=1,
        )
        return {
            "bull_arguments": state["bull_arguments"] + [turn],
            "messages": state["messages"] + [
                AIMessage(content=f"[Bull r{state['round_count']}] {turn.argument}")
            ],
        }

    return node
