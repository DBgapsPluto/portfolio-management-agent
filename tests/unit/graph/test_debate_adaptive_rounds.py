"""Adaptive-round stop conditions for the research_debate sub-graph.

Verifies the 2-signal (confidence + divergence) early-stop logic in
tradingagents.graph.debate_subgraph.build_invest_debate_subgraph.
"""
from tradingagents.agents.researchers.debate_state import InvestDebateState
from tradingagents.graph.debate_subgraph import build_invest_debate_subgraph
from tradingagents.schemas.research import ResearcherTurn


def _bull(conf, tilt):
    return ResearcherTurn(argument="bull", confidence=conf, proposed_risk_tilt=tilt)


def _bear(conf, tilt):
    return ResearcherTurn(argument="bear", confidence=conf, proposed_risk_tilt=tilt)


def _run(bull_seq, bear_seq, max_cap=3):
    """Drive the sub-graph with scripted bull/bear outputs, return round_count."""
    rounds_observed = {"count": 0}

    def fake_bull(state):
        i = rounds_observed["count"]
        return {"bull_arguments": state["bull_arguments"] + [bull_seq[i]]}

    def fake_bear(state):
        i = rounds_observed["count"]
        rounds_observed["count"] += 1
        return {
            "bear_arguments": state["bear_arguments"] + [bear_seq[i]],
            "round_count": state["round_count"] + 1,
        }

    def fake_judge(state):
        return {"bucket_target": None, "research_debate_summary": "ok"}

    sg = build_invest_debate_subgraph(fake_bull, fake_bear, fake_judge, max_rounds_cap=max_cap)
    state = InvestDebateState(
        messages=[], macro_summary="", risk_summary="", technical_summary="", news_summary="",
        bull_arguments=[], bear_arguments=[],
        round_count=0, max_rounds_cap=max_cap,
        bucket_target=None, research_debate_summary="",
    )
    final = sg.invoke(state)
    return final["round_count"]


def test_stops_after_round1_when_both_confident():
    # avg_conf = 0.9 ≥ 0.75 → stop after round 1
    rounds = _run([_bull(0.9, 0.7)], [_bear(0.9, 0.3)])
    assert rounds == 1


def test_stops_after_round1_when_sides_converge():
    # avg_conf = 0.5 (below threshold) but divergence = |0.55 - 0.45| = 0.10 ≤ 0.15 → stop
    rounds = _run([_bull(0.5, 0.55)], [_bear(0.5, 0.45)])
    assert rounds == 1


def test_continues_when_uncertain_and_diverging():
    # Round 1: avg_conf 0.45, div 0.5 → continue
    # Round 2: avg_conf 0.85 → stop
    rounds = _run(
        bull_seq=[_bull(0.5, 0.75), _bull(0.85, 0.65)],
        bear_seq=[_bear(0.4, 0.25), _bear(0.85, 0.35)],
    )
    assert rounds == 2


def test_hard_cap_enforced():
    # Persistent uncertainty + divergence — cap kicks in at round 3
    rounds = _run(
        bull_seq=[_bull(0.4, 0.8)] * 4,
        bear_seq=[_bear(0.4, 0.2)] * 4,
        max_cap=3,
    )
    assert rounds == 3
