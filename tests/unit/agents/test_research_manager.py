from unittest.mock import MagicMock

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.schemas.portfolio import BucketTarget


def test_research_manager_returns_bucket_target():
    deep_llm = MagicMock()
    target = BucketTarget(
        kr_equity=0.15, global_equity=0.30, fx_commodity=0.10,
        bond=0.35, cash_mmf=0.10,
        rationale="recession-disinflation regime, defensive tilt",
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = target

    node = create_research_manager(deep_llm)
    state = {
        "macro_summary": "regime: recession",
        "risk_summary": "VIX 28",
        "technical_summary": "downtrend",
        "news_summary": "events",
        "bull_arguments": ["bull says 60% risk"],
        "bear_arguments": ["bear says 40% risk"],
        "round_count": 1,
    }
    result = node(state)
    assert result["bucket_target"] is target
    assert "research_debate_summary" in result
    assert "위험자산 합" in result["research_debate_summary"]
