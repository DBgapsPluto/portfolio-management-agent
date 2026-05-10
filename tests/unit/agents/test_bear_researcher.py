from unittest.mock import MagicMock

from tradingagents.agents.researchers.bear_researcher import create_bear_researcher


def test_bear_researcher_appends_and_increments_round():
    quick_llm = MagicMock()
    quick_llm.invoke.return_value.content = "안전자산 60% 제안 — yield curve 역전, Sahm rule 트리거."

    node = create_bear_researcher(quick_llm)
    state = {
        "messages": [],
        "macro_summary": "regime: recession_disinflation",
        "risk_summary": "VIX 28, risk_off",
        "technical_summary": "downtrend",
        "news_summary": "FOMC hawkish",
        "bull_arguments": ["bull says 60%"],
        "bear_arguments": [],
        "round_count": 0,
    }
    result = node(state)
    assert len(result["bear_arguments"]) == 1
    assert result["bear_arguments"][0].startswith("안전자산")
    assert result["round_count"] == 1
