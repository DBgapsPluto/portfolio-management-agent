from tradingagents.agents.researchers.debate_state import InvestDebateState


def test_invest_debate_state_init():
    state = InvestDebateState(
        messages=[],
        macro_summary="m", risk_summary="r",
        technical_summary="t", news_summary="n",
        bull_arguments=[], bear_arguments=[],
        round_count=0, max_rounds_cap=3,
        bucket_target=None,
        research_debate_summary="",
    )
    assert state["macro_summary"] == "m"
    assert state["round_count"] == 0
    assert state["bucket_target"] is None
