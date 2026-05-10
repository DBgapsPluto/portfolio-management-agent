from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.registry import register_skill


RISK_BUCKETS = {"위험"}


@register_skill(name="validate_concentration", category="mandate")
def validate_concentration(weights: WeightVector, universe: Universe) -> ValidationReport:
    """Per DB GAPS §2.2: single ETF ≤ 20%, risk asset ≤ 70%."""
    violations = []
    bucket_lookup = {e.ticker: e.bucket for e in universe.etfs}

    for ticker, w in weights.weights.items():
        if w > 0.20 + 1e-6:
            violations.append(Violation(
                rule="single_etf_cap",
                description=f"{ticker} weight {w:.4f} > 0.20",
                severity="hard",
                suggested_fix=f"Reduce {ticker} to ≤0.20",
            ))

    risk_total = sum(
        w for t, w in weights.weights.items()
        if bucket_lookup.get(t) in RISK_BUCKETS
    )
    if risk_total > 0.70 + 1e-6:
        violations.append(Violation(
            rule="risk_asset_cap",
            description=f"Risk weight {risk_total:.4f} > 0.70",
            severity="hard",
            suggested_fix=f"Reduce risk exposure by {(risk_total - 0.70):.4f}",
        ))

    return ValidationReport(passed=not violations, violations=violations)
