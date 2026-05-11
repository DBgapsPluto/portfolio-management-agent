from unittest.mock import MagicMock

from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.schemas.research import ResearcherTurn


def test_bear_researcher_appends_and_increments_round():
    quick_llm = MagicMock()
    bear_turn = ResearcherTurn(
        argument="안전자산 60% 제안 — yield curve 역전, Sahm rule 트리거.",
        confidence=0.72, proposed_risk_tilt=0.35,
    )
    quick_llm.with_structured_output.return_value.invoke.return_value = bear_turn

    bull_turn = ResearcherTurn(argument="bull says 60%", confidence=0.6, proposed_risk_tilt=0.6)

    node = create_bear_researcher(quick_llm)
    state = {
        "messages": [],
        "macro_summary": "regime: recession_disinflation",
        "risk_summary": "VIX 28, risk_off",
        "technical_summary": "downtrend",
        "news_summary": "FOMC hawkish",
        "bull_arguments": [bull_turn],
        "bear_arguments": [],
        "round_count": 0,
    }
    result = node(state)
    assert len(result["bear_arguments"]) == 1
    assert result["bear_arguments"][0].argument.startswith("안전자산")
    assert result["bear_arguments"][0].confidence == 0.72
    assert result["round_count"] == 1
