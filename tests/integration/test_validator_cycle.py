"""Integration test: D4 Validator → Allocator cycle behavior.

Verifies that when validation fails, attempts increment, and at MAX
attempts the fallback path is taken — without requiring real LLMs or APIs.
"""
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingagents.agents.utils.agent_states import _create_empty_state
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.graph.builder import build_main_graph
from tradingagents.graph.conditional_logic import (
    MAX_ALLOCATION_ATTEMPTS, validation_router,
)
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector


def test_pass_routes_to_finalize_unit():
    """Router unit: validation_passed=True → finalize."""
    assert validation_router({"validation_passed": True, "allocation_attempts": 0}) == "finalize"


def test_fail_below_max_routes_to_retry_unit():
    """Router unit: fail with attempts<MAX → retry."""
    assert validation_router({"validation_passed": False, "allocation_attempts": 1}) == "retry_allocator"


def test_fail_at_max_routes_to_fallback_unit():
    """Router unit: fail with attempts==MAX → fallback."""
    state = {"validation_passed": False, "allocation_attempts": MAX_ALLOCATION_ATTEMPTS}
    assert validation_router(state) == "fallback"


def test_full_cycle_with_mocks(tmp_path):
    """End-to-end: violator portfolio → retry → still fails → fallback.

    Mocks all node functions to simulate the cycle without needing LLMs.
    """
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    # Track which nodes ran
    visited: list[str] = []
    allocator_attempts = {"count": 0}

    bad_weights = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A069500": 0.30, "A360750": 0.30, "A411060": 0.10,
                 "A114260": 0.20, "A459580": 0.10},
        rationale="bad: A069500 0.30 violates 20% cap",
    )

    def make_node(agent_id: str):
        def node(state):
            visited.append(agent_id)
            if agent_id in ("macro_quant", "market_risk", "technical", "macro_news"):
                summary_key = {
                    "macro_quant": "macro_summary",
                    "market_risk": "risk_summary",
                    "technical": "technical_summary",
                    "macro_news": "news_summary",
                }[agent_id]
                update = {summary_key: f"{agent_id} ok"}
                if agent_id == "technical":
                    update["correlation_clusters"] = []
                return update
            if agent_id == "research_debate":
                return {"research_debate_summary": "bucket: 30/30/10/20/10",
                        "bucket_target": None}
            if agent_id == "allocator":
                allocator_attempts["count"] += 1
                # Return same bad weights on every retry — guarantees validator fails
                return {
                    "weight_vector": bad_weights,
                    "allocation_attempts": state.get("allocation_attempts", 0) + 1,
                }
            if agent_id == "risk_debate":
                return {"risk_debate_summary": "stub"}
            if agent_id == "validator":
                # Always fail
                return {
                    "validation_passed": False,
                    "validation_report": None,
                    "allocation_feedback": [],
                }
            if agent_id == "fallback":
                return {
                    "weight_vector": bad_weights,
                    "validation_passed": False,
                    "fallback_used": True,
                }
            if agent_id == "portfolio_manager":
                return {"final_portfolio_path": "/tmp/p.json"}
            return {}

        return node

    from tradingagents.presets.spec import PresetSpec, StageSpec, AgentSpec
    preset = PresetSpec(
        name="test", universe="x", capital_krw=1_000_000_000,
        stages=[StageSpec(id="analysts", parallel=True,
                          agents=[AgentSpec(id="macro_quant", skills=[])])],
    )
    graph = build_main_graph(preset, make_node)

    state = _create_empty_state(
        as_of_date="2026-05-25", universe_path=str(universe_json),
        capital_krw=1_000_000_000, preset_name="test",
    )
    final = graph.invoke(state, config={"recursion_limit": 30})

    # Verify cycle behavior
    assert "fallback" in visited, "fallback should have been invoked"
    assert "portfolio_manager" in visited, "portfolio_manager should run after fallback"
    # Allocator should have run multiple times (initial + retries up to MAX)
    assert allocator_attempts["count"] >= 1
    assert allocator_attempts["count"] <= MAX_ALLOCATION_ATTEMPTS + 1
