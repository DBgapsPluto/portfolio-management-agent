from datetime import date

import pandas as pd

from tradingagents.schemas.macro import FinancialConditionsSnapshot
from tradingagents.skills.registry import register_skill


def _classify_regime(nfci: float) -> str:
    """Chicago Fed 공식 해석 기준.

    NFCI 0 = 평균. 표준편차 1 단위로 정규화돼있어 임계가 직접 의미를 가짐.
    """
    if nfci < -0.5:
        return "easy"
    if nfci < 0.5:
        return "neutral"
    if nfci < 1.0:
        return "tight"
    return "crisis"


@register_skill(name="compute_financial_conditions", category="macro")
def compute_financial_conditions(
    nfci_series: pd.Series, anfci_series: pd.Series, as_of: date,
) -> FinancialConditionsSnapshot:
    """NFCI + ANFCI → regime + 4주 추세 기반 tightening flag."""
    nfci = float(nfci_series.iloc[-1])
    anfci = float(anfci_series.iloc[-1])

    # 4주(=약 1개월) 변화. NFCI는 weekly. 5개 미만이면 0.
    if len(nfci_series) >= 5:
        change_4w = float(nfci_series.iloc[-1] - nfci_series.iloc[-5])
    else:
        change_4w = 0.0
    tightening = change_4w > 0.2

    return FinancialConditionsSnapshot(
        nfci=nfci,
        anfci=anfci,
        regime=_classify_regime(nfci),
        tightening=tightening,
        source_date=as_of,
    )
