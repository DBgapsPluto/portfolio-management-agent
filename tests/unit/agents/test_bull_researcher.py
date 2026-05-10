from unittest.mock import MagicMock

from tradingagents.agents.researchers.bull_researcher import create_bull_researcher


def test_bull_researcher_appends_argument():
    quick_llm = MagicMock()
    quick_llm.invoke.return_value.content = "위험자산 65% 제안 — yield curve 정상, momentum 강함."

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
    assert result["bull_arguments"][0].startswith("위험자산")
    assert len(result["messages"]) == 1
