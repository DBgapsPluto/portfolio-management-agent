from pathlib import Path

from tradingagents.agents.validator.mandate_validator import create_mandate_validator
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector


def test_mandate_validator_pass(tmp_path):
    """Test: validator passes on compliant weights."""
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={
            "A069500": 0.20, "A360750": 0.20, "A411060": 0.20,
            "A114260": 0.20, "A459580": 0.20,
        },
        rationale="balanced",
    )
    state = {
        "weight_vector": wv,
        "universe_path": str(universe_json),
        "capital_krw": 1_000_000_000,
        "correlation_clusters": [],
        "previous_portfolio": None,
    }
    node = create_mandate_validator()
    result = node(state)
    # Should pass: all single weights = 0.20, risk asset = 0.60, turnover 100% (initial)
    assert result["validation_passed"] is True
    assert result["allocation_feedback"] == []


def test_mandate_validator_fail_single_cap(tmp_path):
    """Test: validator fails when single ETF exceeds 20% cap."""
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={
            "A069500": 0.25,  # > 20%
            "A360750": 0.15, "A411060": 0.10,
            "A114260": 0.30, "A459580": 0.20,
        },
        rationale="bad",
    )
    state = {
        "weight_vector": wv,
        "universe_path": str(universe_json),
        "capital_krw": 1_000_000_000,
        "correlation_clusters": [],
        "previous_portfolio": None,
    }
    node = create_mandate_validator()
    result = node(state)
    assert result["validation_passed"] is False
    assert len(result["allocation_feedback"]) >= 1
    assert any(v.rule == "single_etf_cap" for v in result["allocation_feedback"])
