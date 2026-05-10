import pytest
from pydantic import ValidationError
from tradingagents.schemas.reports import (
    MacroReport, RiskReport, TechnicalReport, NewsReport,
)
from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    DivergenceScore, RegimeClassification,
)


def test_macro_report_narrative_max_length():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=-25.0, spread_10y_3m_bps=-30.0,
        inverted_days_count=120, percentile_5y=0.05,
    )
    infl = InflationSnapshot(
        cpi_yoy=2.8, core_cpi_yoy=3.2, momentum_3mo=2.5,
        momentum_6mo=3.0, accelerating=False,
    )
    emp = EmploymentSnapshot(
        unemployment_rate=4.2, rate_change_3mo=0.5,
        sahm_rule_triggered=True, non_farm_payrolls_3mo_avg=140_000,
    )
    div = DivergenceScore(us_kr_rate_gap_bps=200.0, us_kr_inflation_gap=0.5, score=2.5)
    regime = RegimeClassification(
        quadrant="recession_disinflation", confidence=0.85,
        drivers=["yield curve"], reasoning="x",
    )
    report = MacroReport(
        yield_curve=yc, inflation=infl, employment=emp,
        kr_divergence=div, regime=regime,
        upcoming_events=[], narrative="짧은 매크로 요약",
        summary_for_downstream="recession-disinflation, 35% risk asset",
    )
    assert len(report.narrative) <= 500


def test_narrative_too_long_rejected():
    with pytest.raises(ValidationError):
        MacroReport.model_validate({
            "yield_curve": {"spread_10y_2y_bps": 0, "spread_10y_3m_bps": 0,
                            "inverted_days_count": 0, "percentile_5y": 0.5},
            "inflation": {"cpi_yoy": 0, "core_cpi_yoy": 0, "momentum_3mo": 0,
                          "momentum_6mo": 0, "accelerating": False},
            "employment": {"unemployment_rate": 0, "rate_change_3mo": 0,
                           "sahm_rule_triggered": False, "non_farm_payrolls_3mo_avg": 0},
            "kr_divergence": {"us_kr_rate_gap_bps": 0, "us_kr_inflation_gap": 0, "score": 0},
            "regime": {"quadrant": "growth_inflation", "confidence": 0.5,
                       "drivers": ["x"], "reasoning": "y"},
            "upcoming_events": [],
            "narrative": "x" * 501,
            "summary_for_downstream": "y",
        })
