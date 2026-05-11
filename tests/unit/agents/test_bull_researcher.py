from unittest.mock import MagicMock

from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.schemas.research import ResearcherTurn


def test_bull_researcher_appends_structured_turn():
    quick_llm = MagicMock()
    turn = ResearcherTurn(
        argument="위험자산 65% 제안 — yield curve 정상, momentum 강함.",
        confidence=0.78, proposed_risk_tilt=0.65,
    )
    quick_llm.with_structured_output.return_value.invoke.return_value = turn

    node = create_bull_researcher(quick_llm)
    state = {
        "messages": [],
        "macro_summary": "regime: growth_inflation",
        "risk_summary": "VIX 18, risk_on",
        "technical_summary": "momentum top",
        "news_summary": "FOMC dovish",
        "bear_arguments": [],
        "bull_arguments": [],
        "round_count": 0,
    }
    result = node(state)
    assert len(result["bull_arguments"]) == 1
    assert result["bull_arguments"][0].argument.startswith("위험자산")
    assert result["bull_arguments"][0].confidence == 0.78
    assert result["bull_arguments"][0].proposed_risk_tilt == 0.65
    assert len(result["messages"]) == 1
