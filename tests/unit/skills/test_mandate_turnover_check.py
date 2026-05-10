from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.mandate.turnover_check import validate_turnover_feasibility


def _wv() -> WeightVector:
    return WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A1": 0.5, "A2": 0.5},
        rationale="x",
    )


def test_initial_setup_meets_80pct_floor():
    """Initial: weights sum to 1.0, all buys → turnover = 100%."""
    rep = validate_turnover_feasibility(
        _wv(), previous_weights=None,
        capital_krw=1_000_000_000, floor_pct=0.80, days_remaining=5,
    )
    assert rep.passed is True


def test_no_change_fails_monthly_10pct_floor():
    """Same weights as previous → 0% turnover, fails 10% monthly floor."""
    rep = validate_turnover_feasibility(
        _wv(), previous_weights={"A1": 0.5, "A2": 0.5},
        capital_krw=1_000_000_000, floor_pct=0.10, days_remaining=20,
    )
    assert rep.passed is False
    assert any(v.rule == "turnover_floor" for v in rep.violations)
