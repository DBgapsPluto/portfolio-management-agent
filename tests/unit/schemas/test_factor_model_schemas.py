"""Stage 1 enhance 의 신규 schema fields 검증 (C3-C4 — factor model F1 / F4 components)."""
from datetime import date

from tradingagents.schemas.macro import FinancialConditionsSnapshot, YieldCurveSnapshot


def test_financial_conditions_has_cfnai_field():
    """cfnai field 가 default 0.0."""
    fci = FinancialConditionsSnapshot(
        nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
        source_date=date.today(),
    )
    assert fci.cfnai == 0.0
    assert fci.cfnai_3m_avg == 0.0


def test_financial_conditions_accepts_cfnai_value():
    fci = FinancialConditionsSnapshot(
        nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
        source_date=date.today(),
        cfnai=+0.5,
        cfnai_3m_avg=+0.3,
    )
    assert fci.cfnai == +0.5
    assert fci.cfnai_3m_avg == +0.3


def test_yield_curve_has_spread_30y_5y_field():
    """spread_30y_5y_bps field 가 default 0.0 (C4 — F4 term_premium component)."""
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
        inverted_days_count=0, percentile_5y=0.5,
        source_date=date.today(),
    )
    assert yc.spread_30y_5y_bps == 0.0


def test_yield_curve_accepts_spread_30y_5y():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
        inverted_days_count=0, percentile_5y=0.5,
        source_date=date.today(),
        spread_30y_5y_bps=120.0,
    )
    assert yc.spread_30y_5y_bps == 120.0
