"""Mandate Validator — runs all 4 deterministic checks; wires D4 cycle."""
from pathlib import Path

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.mandate import ValidationReport, Violation
from tradingagents.skills.mandate.concentration_check import validate_concentration
from tradingagents.skills.mandate.correlation_check import validate_correlation_concentration
from tradingagents.skills.mandate.turnover_check import validate_turnover_feasibility
from tradingagents.skills.mandate.universe_check import validate_universe


def create_mandate_validator():
    """Factory for Mandate Validator node.

    Returns a node function that:
    - Takes state with weight_vector, universe_path, capital_krw, correlation_clusters, previous_portfolio
    - Runs 4 deterministic checks (universe, concentration, correlation, turnover)
    - Returns state updates with validation_passed bool and allocation_feedback (hard violations)
    """
    def node(state):
        weights = state.get("weight_vector")
        if weights is None:
            return {
                "validation_passed": False,
                "validation_report": ValidationReport(
                    passed=False,
                    violations=[Violation(
                        rule="universe_membership",
                        description="No weight_vector to validate",
                        severity="hard",
                        suggested_fix="Re-run Allocator",
                    )],
                ),
                "allocation_feedback": [],
            }

        universe = load_universe(Path(state["universe_path"]))
        all_violations = []

        # Run universe check
        universe_result = validate_universe(weights, universe)
        all_violations.extend(universe_result.violations)

        # Run concentration check
        concentration_result = validate_concentration(weights, universe)
        all_violations.extend(concentration_result.violations)

        # Run correlation concentration check
        correlation_clusters = state.get("correlation_clusters", [])
        correlation_result = validate_correlation_concentration(weights, correlation_clusters)
        all_violations.extend(correlation_result.violations)

        # Run turnover check
        previous_portfolio = state.get("previous_portfolio")
        prev_weights = previous_portfolio.get("weights") if previous_portfolio else None
        # Per design spec: initial run (5/28 → 6/8) uses 80% floor with 5 days
        # Rebalancing (with previous_portfolio) uses 10% floor with 20 days
        floor_pct = 0.10 if previous_portfolio else 0.80
        days_remaining = 20 if previous_portfolio else 5
        turnover_result = validate_turnover_feasibility(
            weights, prev_weights, state["capital_krw"],
            floor_pct=floor_pct, days_remaining=days_remaining,
        )
        all_violations.extend(turnover_result.violations)

        # Build report
        report = ValidationReport(
            passed=not any(v.severity == "hard" for v in all_violations),
            violations=all_violations,
        )
        return {
            "validation_report": report,
            "validation_passed": report.passed,
            "allocation_feedback": report.hard_violations if not report.passed else [],
        }

    return node
