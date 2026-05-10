from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.registry import register_skill


@register_skill(name="validate_universe", category="mandate")
def validate_universe(weights: WeightVector, universe: Universe) -> ValidationReport:
    universe_tickers = {e.ticker for e in universe.etfs}
    violations = []
    for ticker in weights.weights:
        if ticker not in universe_tickers:
            violations.append(Violation(
                rule="universe_membership",
                description=f"{ticker} not in 188 universe",
                severity="hard",
                suggested_fix=f"Remove {ticker}",
            ))
    return ValidationReport(passed=not violations, violations=violations)
