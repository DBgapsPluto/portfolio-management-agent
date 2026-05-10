from datetime import date

import pandas as pd

from tradingagents.schemas.macro import InflationSnapshot
from tradingagents.skills.registry import register_skill


def _annualized(series: pd.Series, months: int) -> float:
    if len(series) < months + 1:
        return 0.0
    pct = (series.iloc[-1] / series.iloc[-1 - months]) ** (12 / months) - 1
    return float(pct * 100)


@register_skill(name="compute_inflation_trend", category="macro")
def compute_inflation_trend(
    cpi: pd.Series, core_cpi: pd.Series, as_of: date,
) -> InflationSnapshot:
    yoy = _annualized(cpi, 12)
    core_yoy = _annualized(core_cpi, 12)
    m3 = _annualized(cpi, 3)
    m6 = _annualized(cpi, 6)
    accelerating = m3 > m6 > yoy

    return InflationSnapshot(
        cpi_yoy=yoy,
        core_cpi_yoy=core_yoy,
        momentum_3mo=m3,
        momentum_6mo=m6,
        accelerating=accelerating,
        source_date=as_of,
    )
