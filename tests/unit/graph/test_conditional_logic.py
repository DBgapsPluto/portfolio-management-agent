"""D4 cycle: router + fallback tests."""
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.graph.conditional_logic import (
    validation_router, MAX_ALLOCATION_ATTEMPTS,
    create_fallback_normalizer, _emergency_cash_portfolio,
)
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector


def test_pass_routes_to_finalize():
    state = {"validation_passed": True, "allocation_attempts": 1}
    assert validation_router(state) == "finalize"


def test_fail_attempt_1_retries():
    state = {"validation_passed": False, "allocation_attempts": 1}
    assert validation_router(state) == "retry_allocator"


def test_fail_attempt_max_falls_back():
    state = {"validation_passed": False, "allocation_attempts": MAX_ALLOCATION_ATTEMPTS}
    assert validation_router(state) == "fallback"


def test_emergency_cash_portfolio_uses_safe_etfs(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    state = {
        "universe_path": str(universe_json),
        "allocation_attempts": 2,
    }
    result = _emergency_cash_portfolio(state)
    assert result["validation_passed"] is False
    assert result.get("fallback_used") is True
    new_wv = result["weight_vector"]
    # Test fixture has only 2 safe ETFs (1 bond + 1 MMF) → 50% each.
    # In real universe with ≥5 safe ETFs, each ≤ 20%.
    assert abs(sum(new_wv.weights.values()) - 1.0) < 1e-6
    # Verify only 안전 ETFs are present (no 위험 bucket leakage).
    safe_tickers = {"A114260", "A459580"}  # from test fixture
    assert set(new_wv.weights.keys()).issubset(safe_tickers)


def test_fallback_re_optimizes_with_constraints(tmp_path):
    """Fallback re-runs min-variance with strict weight_bounds (D4 fix)."""
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    bad_weights = WeightVector(
        method=OptimizationMethod.HRP,
        weights={
            "A069500": 0.30, "A360750": 0.25,
            "A411060": 0.20, "A114260": 0.15, "A459580": 0.10,
        },  # A069500 violates 20% cap
        rationale="bad",
    )
    state = {
        "weight_vector": bad_weights,
        "universe_path": str(universe_json),
        "as_of_date": "2026-05-10",
        "allocation_attempts": 2,
    }

    fake_returns = pd.DataFrame({
        "A069500": [0.001, -0.002, 0.003] * 100,
        "A360750": [0.002, -0.001, 0.002] * 100,
        "A411060": [0.0, 0.001, 0.0] * 100,
        "A114260": [-0.001, 0.001, -0.002] * 100,
        "A459580": [0.0, 0.0001, 0.0] * 100,
    })

    fb = create_fallback_normalizer()
    with patch("tradingagents.graph.conditional_logic.fetch_returns_matrix",
               return_value=fake_returns):
        result = fb(state)

    new_wv = result["weight_vector"]
    assert all(w <= 0.20 + 1e-6 for w in new_wv.weights.values())
    assert abs(sum(new_wv.weights.values()) - 1.0) < 1e-3
    assert result["validation_passed"] is False
    assert result.get("fallback_used") is True


def test_contract_mode_skips_retry_goes_to_fallback():
    from tests.integration._allocator_state_helpers import (
        make_research_decision_with_contract,
        make_synthetic_universe,
    )

    universe = make_synthetic_universe(n_per_bucket=2)
    rd = make_research_decision_with_contract(universe)
    state = {
        "validation_passed": False,
        "allocation_attempts": 1,
        "research_decision": rd,
        "config": {
            "allocation_contract_enabled": True,
            "contract_skip_allocator_retry": True,
        },
    }
    assert validation_router(state) == "fallback"


def test_fallback_used_routes_to_finalize():
    state = {
        "validation_passed": False,
        "allocation_attempts": 3,
        "fallback_used": True,
    }
    assert validation_router(state) == "finalize"
