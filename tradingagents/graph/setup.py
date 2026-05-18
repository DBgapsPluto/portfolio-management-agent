# TradingAgents/graph/setup.py — legacy v0.2 upstream path (NOT USED by db_gaps).
#
# db_gaps preset은 `tradingagents.graph.builder.build_main_graph` + sub-graph
# 패턴을 사용한다. 이 모듈은 upstream v0.2 호환을 위해 stub로 보존되며,
# Phase 1 (Bull/Bear 토론 폐기) 이후 Bull/Bear/Trader 등 v0.2 노드는 우리
# 코드베이스에서 제거되었으므로 setup_graph() 호출 시 즉시 실패한다.
from typing import Any, Dict

from langgraph.prebuilt import ToolNode

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Deprecated v0.2 upstream graph setup. db_gaps에서 미사용."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
    ):
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def setup_graph(self, selected_analysts=None):
        raise NotImplementedError(
            "graph.setup.GraphSetup is the legacy v0.2 upstream path. "
            "Use tradingagents.graph.trading_graph.TradingAgentsGraph + "
            "build_main_graph for the db_gaps pipeline."
        )
