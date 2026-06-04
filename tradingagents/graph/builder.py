"""Build a LangGraph from a PresetSpec (D3) — main pipeline composition."""
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.graph.conditional_logic import validation_router


def build_main_graph(preset, node_factory):
    """Build the top-level graph from a preset.

    `node_factory` is a callable: agent_id (str) → node function. This
    indirection lets tests inject mock nodes; production wires real nodes.

    Expected node IDs the factory must support:
      - macro_quant, market_risk, technical, macro_news (analyst stage, parallel)
      - research_debate (wraps invest sub-graph)
      - allocator
      - risk_debate (wraps risk sub-graph; can be pass-through stub)
      - validator
      - fallback
      - portfolio_manager
    """
    sg = StateGraph(AgentState)

    # Stage 1: parallel analysts
    analyst_ids = ["macro_quant", "market_risk", "technical", "macro_news"]
    for agent_id in analyst_ids:
        sg.add_node(agent_id, node_factory(agent_id))
        sg.add_edge(START, agent_id)

    # Stage 2: research debate (single node — sub-graph wrapped inside)
    sg.add_node("research_debate", node_factory("research_debate"))
    for agent_id in analyst_ids:
        sg.add_edge(agent_id, "research_debate")

    # Stage 3: allocator
    sg.add_node("allocator", node_factory("allocator"))
    sg.add_edge("research_debate", "allocator")

    # Stage 4: risk debate (sub-graph wrapped)
    sg.add_node("risk_debate", node_factory("risk_debate"))
    sg.add_edge("allocator", "risk_debate")

    # Stage 5: validator
    sg.add_node("validator", node_factory("validator"))
    sg.add_edge("risk_debate", "validator")

    # Stage 6: D4 cycle conditional
    sg.add_node("fallback", node_factory("fallback"))
    sg.add_node("portfolio_manager", node_factory("portfolio_manager"))

    sg.add_conditional_edges(
        "validator", validation_router,
        {
            "finalize": "portfolio_manager",
            "retry_allocator": "allocator",
            "fallback": "fallback",
        },
    )
    sg.add_edge("fallback", "validator")
    sg.add_edge("portfolio_manager", END)

    return sg.compile()
