"""AgentState LangGraph 채널 선언 회귀.

LangGraph StateGraph 는 선언된 채널만 merge 하고 미선언 키는 조용히 drop 한다.
mandate_validator_attribution 이 AgentState 채널에서 빠져있어, validator 가 set 해도
graph state 에 안 들어가고 portfolio.json 의 해당 키가 항상 null 이었다 (E2E 2026-06-04).
단위 테스트(노드 직접 호출)는 이 클래스의 버그를 못 잡으므로 compiled graph 로 검증한다.
"""
from langgraph.graph import END, START, StateGraph

from tradingagents.agents.utils.agent_states import AgentState, _create_empty_state


def test_mandate_validator_attribution_survives_compiled_graph():
    """validator 가 set 한 mandate_validator_attribution 이 최종 state 까지 전파돼야."""
    sentinel = {"passed": True, "rules": ["universe", "concentration"]}

    def setter(state):
        return {"mandate_validator_attribution": sentinel}

    def passthrough(state):
        return {}

    g = StateGraph(AgentState)
    g.add_node("setter", setter)
    g.add_node("passthrough", passthrough)
    g.add_edge(START, "setter")
    g.add_edge("setter", "passthrough")
    g.add_edge("passthrough", END)
    app = g.compile()

    state = _create_empty_state(
        "2026-06-04", "data/universe.json", 1_000_000_000, "default",
    )
    out = app.invoke(state)

    assert out.get("mandate_validator_attribution") == sentinel
