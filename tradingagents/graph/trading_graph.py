"""TradingAgentsGraph — preset-driven entry point for the DB GAPS pipeline."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from tradingagents.agents.analysts.macro_news_analyst import create_macro_news_analyst
from tradingagents.agents.analysts.macro_quant_analyst import create_macro_quant_analyst
from tradingagents.agents.analysts.market_risk_analyst import create_market_risk_analyst
from tradingagents.agents.analysts.technical_analyst import create_technical_analyst
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.researchers.research_cluster import create_research_cluster
from tradingagents.agents.trader.trader_allocator import create_trader_allocator
from tradingagents.agents.utils.agent_states import _create_empty_state
from tradingagents.agents.validator.mandate_validator import create_mandate_validator
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.builder import build_main_graph
from tradingagents.graph.conditional_logic import create_fallback_normalizer
from tradingagents.llm_clients import create_llm_client
from tradingagents.observability.run_archive import (
    archive_metadata, archive_wrap_node,
)
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

        # Stage 1 analysts — 출력을 runs/{as_of_date}/{*_report}.json + *_summary.txt에 archive.
        analysts = {
            "macro_quant": archive_wrap_node(
                create_macro_quant_analyst(quick, deep),
                ["macro_report", "macro_summary"],
            ),
            "market_risk": archive_wrap_node(
                create_market_risk_analyst(quick, deep),
                ["risk_report", "risk_summary"],
            ),
            "technical": archive_wrap_node(
                create_technical_analyst(quick, deep, cache_path=cache_path),
                ["technical_report", "technical_summary"],
            ),
            "macro_news": archive_wrap_node(
                create_macro_news_analyst(quick, deep),
                ["news_report", "news_summary"],
            ),
        }

        # Stage 2: bull/bear/manager 클러스터 (단일 패스). 모델은 전부 deep(gpt-5.5).
        research_debate_node = create_research_cluster(
            bull_llm=deep, bear_llm=deep, manager_llm=deep,
        )

        allocator = archive_wrap_node(
            create_trader_allocator(step_a_llm=deep, step_b_llm=deep),
            ["candidate_set", "weight_vector", "method_choice",
             "allocation_attribution", "bucket_target"],
        )
        validator = create_mandate_validator()
        fallback = create_fallback_normalizer(cache_path=cache_path)
        pm = create_portfolio_manager(deep, artifacts_dir=artifacts_dir)

        # Stage 4 (risk overlay) 제거 — allocator → validator 직결.

        # Stage 2 research_decision도 archive (Stage 2 Phase 1 산출물).
        research_debate_node = archive_wrap_node(
            research_debate_node,
            ["research_decision", "research_debate_summary"],
        )

        validator = archive_wrap_node(
            validator,
            ["validation_report", "rebalance_mode"],
        )

        nodes = {
            **analysts,
            "research_debate": research_debate_node,
            "allocator": allocator,
            "validator": validator,
            "fallback": fallback,
            "portfolio_manager": pm,
        }
        # Exposed for stage-isolated replay (scripts/replay_stage.py).
        self.nodes = nodes

        def factory(agent_id: str):
            return nodes.get(agent_id, lambda s: s)

        self.graph = build_main_graph(self.preset, factory)

    def run(
        self,
        as_of_date: str,
        capital_krw: int = 1_000_000_000,
        previous_portfolio: Optional[dict] = None,
        force_method: Optional[str] = None,
    ) -> dict:
        state = _create_empty_state(
            as_of_date=as_of_date,
            universe_path=self.config["universe_path"],
            capital_krw=capital_krw,
            preset_name=self.preset_name,
            previous_portfolio=previous_portfolio,
            force_method=force_method,
        )
        try:
            archive_metadata(as_of_date, {
                "preset": self.preset_name,
                "capital_krw": capital_krw,
                "deep_llm": self.config.get("deep_think_llm"),
                "quick_llm": self.config.get("quick_think_llm"),
            })
        except Exception as e:
            logger.warning("metadata archive failed: %s", e)
        return self.graph.invoke(state, config={"recursion_limit": 50})
