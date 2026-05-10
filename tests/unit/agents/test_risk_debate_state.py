from tradingagents.agents.risk_mgmt.debate_state import RiskDebateState


def test_risk_debate_state_init():
    state = RiskDebateState(
        messages=[],
        weight_vector_input=None,
        correlation_clusters_summary="",
        macro_summary="m", risk_summary="r",
        aggressive_arguments=[], conservative_arguments=[], neutral_arguments=[],
        round_count=0, max_rounds=1,
        weight_adjustment=None,
        risk_debate_summary="",
    )
    assert state["macro_summary"] == "m"
    assert state["round_count"] == 0
    assert state["weight_adjustment"] is None
