"""Stage 1 enhance 의 신규 schema fields 검증 (C3 — factor model F1 components)."""
from datetime import date

from tradingagents.schemas.macro import FinancialConditionsSnapshot


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
