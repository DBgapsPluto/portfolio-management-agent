from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.registry import register_skill


@register_skill(name="validate_turnover_feasibility", category="mandate")
def validate_turnover_feasibility(
    proposed: WeightVector,
    previous_weights: dict[str, float] | None,
    capital_krw: int,
    floor_pct: float,
    days_remaining: int,
) -> ValidationReport:
    """Check if proposed weights produce ≥floor_pct turnover.

    For initial setup (5/28 → 6/8): floor_pct=0.80, days_remaining=5.
    For monthly: floor_pct=0.10, days_remaining=20.
    """
    if previous_weights is None:
        # Initial: all weights are buys
        buy_amount = sum(proposed.weights.values()) * capital_krw
        sell_amount = 0
    else:
        all_tickers = set(proposed.weights) | set(previous_weights)
        delta = {t: proposed.weights.get(t, 0) - previous_weights.get(t, 0) for t in all_tickers}
        buy_amount = sum(d for d in delta.values() if d > 0) * capital_krw
        sell_amount = -sum(d for d in delta.values() if d < 0) * capital_krw

    avg_assets = capital_krw  # simplified
    turnover = (buy_amount + sell_amount) / avg_assets

    violations = []
    if turnover < floor_pct:
        violations.append(Violation(
            rule="turnover_floor",
            description=f"Planned turnover {turnover:.4f} < floor {floor_pct}",
            severity="hard",
            suggested_fix=f"Increase trade size by {(floor_pct - turnover):.4f}",
        ))
    return ValidationReport(passed=not violations, violations=violations)
