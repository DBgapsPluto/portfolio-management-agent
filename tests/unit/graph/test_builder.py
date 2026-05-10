"""Tests for build_main_graph."""
from tradingagents.agents.utils.agent_states import _create_empty_state
from tradingagents.graph.builder import build_main_graph
from tradingagents.presets.spec import (
    PresetSpec, AgentSpec, StageSpec, ClusterMode,
)


def _minimal_preset() -> PresetSpec:
    return PresetSpec(
        name="test", universe="x", capital_krw=1_000_000_000,
        stages=[
            StageSpec(
                id="analysts", parallel=True,
                agents=[AgentSpec(id="macro_quant", skills=[])],
            ),
        ],
    )


def test_build_main_graph_compiles():
    """Graph compiles with mocked node_factory."""
    visited = []

    def make_node(agent_id):
        def node(state):
            visited.append(agent_id)
            # Provide the minimum keys downstream nodes need
            if agent_id == "macro_quant":
                return {"macro_summary": "macro"}
            if agent_id == "market_risk":
                return {"risk_summary": "risk"}
            if agent_id == "technical":
                return {"technical_summary": "tech", "correlation_clusters": []}
            if agent_id == "macro_news":
                return {"news_summary": "news"}
            if agent_id == "research_debate":
                return {"research_debate_summary": "60/40", "bucket_target": None}
            if agent_id == "allocator":
                return {"weight_vector": None, "allocation_attempts": 1}
            if agent_id == "risk_debate":
                return {"risk_debate_summary": "ok"}
            if agent_id == "validator":
                # Force pass for this smoke test
                return {"validation_passed": True, "validation_report": None,
                        "allocation_feedback": []}
            if agent_id == "portfolio_manager":
                return {"final_portfolio_path": "/tmp/p.json"}
            return {}

        return node

    preset = _minimal_preset()
    graph = build_main_graph(preset, make_node)

    state = _create_empty_state(
        as_of_date="2026-05-25", universe_path="x",
        capital_krw=100, preset_name="test",
    )
    final = graph.invoke(state, config={"recursion_limit": 25})

    # Verify the routing reached portfolio_manager (validator passed)
    assert "portfolio_manager" in visited
    assert final.get("final_portfolio_path") == "/tmp/p.json"

    # All 4 analysts ran in parallel before research_debate
    analyst_ids = {"macro_quant", "market_risk", "technical", "macro_news"}
    assert analyst_ids.issubset(set(visited))


def test_build_main_graph_routes_to_fallback_on_max_attempts():
    """When validator fails and attempts hit MAX, route to fallback."""
    visited = []

    def make_node(agent_id):
        def node(state):
            visited.append(agent_id)
            if agent_id in ("macro_quant", "market_risk", "technical", "macro_news"):
                if agent_id == "technical":
                    return {"technical_summary": "x", "correlation_clusters": []}
                key = {"macro_quant": "macro_summary", "market_risk": "risk_summary",
                       "macro_news": "news_summary"}[agent_id]
                return {key: "x"}
            if agent_id == "research_debate":
                return {"research_debate_summary": "x", "bucket_target": None}
            if agent_id == "allocator":
                # Bump attempts to MAX so validator fail routes to fallback
                attempts = state.get("allocation_attempts", 0) + 1
                return {"weight_vector": None, "allocation_attempts": attempts}
            if agent_id == "risk_debate":
                return {"risk_debate_summary": "x"}
            if agent_id == "validator":
                return {"validation_passed": False, "validation_report": None,
                        "allocation_feedback": []}
            if agent_id == "fallback":
                return {"validation_passed": True}
            if agent_id == "portfolio_manager":
                return {"final_portfolio_path": "/tmp/p.json"}
            return {}

        return node

    preset = _minimal_preset()
    graph = build_main_graph(preset, make_node)

    state = _create_empty_state(
        as_of_date="2026-05-25", universe_path="x",
        capital_krw=100, preset_name="test",
    )
    # Pre-set attempts to MAX so first allocator pass triggers fallback after validator
    state["allocation_attempts"] = 2  # MAX_ALLOCATION_ATTEMPTS
    final = graph.invoke(state, config={"recursion_limit": 30})

    # fallback should have been invoked
    assert "fallback" in visited
    assert "portfolio_manager" in visited
