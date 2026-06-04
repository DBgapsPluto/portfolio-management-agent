"""새 노드가 trading_graph 에 배선됐는지 — LLM 호출 없이 nodes dict 만 검증."""
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_research_and_allocator_nodes_exist():
    g = TradingAgentsGraph(preset_name="db_gaps")
    assert "research_debate" in g.nodes
    assert "allocator" in g.nodes
    assert callable(g.nodes["research_debate"])
    assert callable(g.nodes["allocator"])
