import pytest
from pydantic import ValidationError
from tradingagents.schemas.macro import (
    YieldCurveSnapshot,
    InflationSnapshot,
    EmploymentSnapshot,
    RegimeClassification,
    DivergenceScore,
    CentralBankEvent,
)


def test_yield_curve_inverted():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=-25.5,
        spread_10y_3m_bps=-40.0,
        inverted_days_count=120,
        percentile_5y=0.05,
    )
    assert yc.spread_10y_2y_bps < 0


def test_regime_classification_enum():
    rc = RegimeClassification(
        quadrant="recession_disinflation",
        confidence=0.85,
        drivers=["yield curve inversion", "rising unemployment"],
        reasoning="Sahm rule triggered, 10y-2y at -25bp",
    )
    assert rc.quadrant == "recession_disinflation"
    assert 0 <= rc.confidence <= 1


def test_regime_rejects_bad_quadrant():
    with pytest.raises(ValidationError):
        RegimeClassification(
            quadrant="random_string",
            confidence=0.5,
            drivers=["x"],
            reasoning="y",
        )


def test_employment_with_sahm():
    emp = EmploymentSnapshot(
        unemployment_rate=4.2,
        rate_change_3mo=0.5,
        sahm_rule_triggered=True,
        non_farm_payrolls_3mo_avg=150_000,
    )
    assert emp.sahm_rule_triggered is True
