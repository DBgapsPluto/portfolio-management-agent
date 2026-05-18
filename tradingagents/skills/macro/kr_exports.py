from datetime import date

import pandas as pd

from tradingagents.schemas.macro import KRExportSnapshot
from tradingagents.skills.registry import register_skill


def _annualized(series: pd.Series, months: int) -> float:
    if len(series) < months + 1:
        return 0.0
    base = series.iloc[-1 - months]
    if base == 0:
        return 0.0
    pct = (series.iloc[-1] / base) ** (12 / months) - 1
    return float(pct * 100)


@register_skill(name="compute_kr_export_trend", category="macro")
def compute_kr_export_trend(export_value: pd.Series, as_of: date) -> KRExportSnapshot:
    """월간 수출액으로 YoY + 3/6개월 모멘텀 + 가속 플래그 산출."""
    yoy = _annualized(export_value, 12)
    m3 = _annualized(export_value, 3)
    m6 = _annualized(export_value, 6)
    accelerating = m3 > m6 > yoy

    return KRExportSnapshot(
        yoy_pct=yoy,
        momentum_3mo_pct=m3,
        momentum_6mo_pct=m6,
        accelerating=accelerating,
        source_date=as_of,
    )
