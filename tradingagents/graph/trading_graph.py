"""TradingAgentsGraph — preset-driven entry point for the DB GAPS pipeline."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator
from tradingagents.agents.analysts.macro_news_analyst import create_macro_news_analyst
from tradingagents.agents.analysts.macro_quant_analyst import create_macro_quant_analyst
from tradingagents.agents.analysts.market_risk_analyst import create_market_risk_analyst
from tradingagents.agents.analysts.technical_analyst import create_technical_analyst
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.researchers.debate_state import InvestDebateState
from tradingagents.agents.utils.agent_states import _create_empty_state
from tradingagents.agents.validator.mandate_validator import create_mandate_validator
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.builder import build_main_graph
from tradingagents.graph.conditional_logic import create_fallback_normalizer
from tradingagents.graph.debate_subgraph import build_invest_debate_subgraph
from tradingagents.llm_clients import create_llm_client
from tradingagents.presets.loader import PresetLoader
import tradingagents.skills._registry_init  # noqa: F401 — register all skills

logger = logging.getLogger(__name__)


class TradingAgentsGraph:
    """Main entry point. Loads a preset, instantiates LLMs + nodes, runs the graph."""

    def __init__(
        self,
        preset_name: str = "db_gaps",
        config: Optional[dict[str, Any]] = None,
    ):
        self.config = config or DEFAULT_CONFIG
        self.preset_name = preset_name

        preset_path = Path(self.config["preset_dir"]) / f"{preset_name}.yaml"
        self.preset = PresetLoader.from_yaml(preset_path)

        # Build LLMs
        deep = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
        ).get_llm()
        quick = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
        ).get_llm()

        # Assemble nodes
        cache_path = self.config.get("etf_price_cache_path")
        artifacts_dir = self.config.get("artifacts_dir", "./artifacts")

        analysts = {
            "macro_quant": create_macro_quant_analyst(quick, deep),
            "market_risk": create_market_risk_analyst(quick, deep),
            "technical": create_technical_analyst(quick, deep, cache_path=cache_path),
            "macro_news": create_macro_news_analyst(quick, deep),
        }

        bull = create_bull_researcher(quick)
        bear = create_bear_researcher(quick)
        research_judge = create_research_manager(deep)
        invest_subgraph = build_invest_debate_subgraph(
            bull, bear, research_judge,
            max_rounds=self.config.get("max_debate_rounds", 1),
        )

        allocator = create_portfolio_allocator(quick, deep, cache_path=cache_path)
        validator = create_mandate_validator()
        fallback = create_fallback_normalizer(cache_path=cache_path)
        pm = create_portfolio_manager(deep, artifacts_dir=artifacts_dir)

        # Wrap research_debate as a parent node that invokes the sub-graph
        max_rounds = self.config.get("max_debate_rounds", 1)
        def research_debate_node(state):
            sub_input = InvestDebateState(
                messages=[],
                macro_summary=state.get("macro_summary", ""),
                risk_summary=state.get("risk_summary", ""),
                technical_summary=state.get("technical_summary", ""),
                news_summary=state.get("news_summary", ""),
                bull_arguments=[], bear_arguments=[],
                round_count=0, max_rounds=max_rounds,
                bucket_target=None,
                research_debate_summary="",
            )
            sub_result = invest_subgraph.invoke(sub_input)
            return {
                "research_debate_summary": sub_result.get("research_debate_summary", ""),
                "bucket_target": sub_result.get("bucket_target"),
            }

        # risk_debate as pass-through stub for Plan 3 (Plan 4 wires sub-graph)
        def risk_debate_stub(state):
            return {"risk_debate_summary": "(risk debate stub — Plan 4 wires)"}

        nodes = {
            **analysts,
            "research_debate": research_debate_node,
            "allocator": allocator,
            "risk_debate": risk_debate_stub,
            "validator": validator,
            "fallback": fallback,
            "portfolio_manager": pm,
        }

        def factory(agent_id: str):
            return nodes.get(agent_id, lambda s: s)

        self.graph = build_main_graph(self.preset, factory)

    def run(
        self,
        as_of_date: str,
        capital_krw: int = 1_000_000_000,
        previous_portfolio: Optional[dict] = None,
    ) -> dict:
        state = _create_empty_state(
            as_of_date=as_of_date,
            universe_path=self.config["universe_path"],
            capital_krw=capital_krw,
            preset_name=self.preset_name,
            previous_portfolio=previous_portfolio,
        )
        return self.graph.invoke(state, config={"recursion_limit": 50})
