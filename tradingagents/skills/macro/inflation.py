from datetime import date

import pandas as pd

from tradingagents.schemas.macro import InflationSnapshot
from tradingagents.skills.registry import register_skill


def _annualized(series: pd.Series, months: int) -> float:
    if len(series) < months + 1:
        return 0.0
    base = series.iloc[-1 - months]
    if base == 0:
        return 0.0
    pct = (series.iloc[-1] / base) ** (12 / months) - 1
    return float(pct * 100)


@register_skill(name="compute_inflation_trend", category="macro")
def compute_inflation_trend(
    cpi: pd.Series, core_cpi: pd.Series, as_of: date,
    pce: pd.Series | None = None, core_pce: pd.Series | None = None,
) -> InflationSnapshot:
    """CPI + Core CPI + (2026-05 추가) PCE / Core PCE 정상화.

    PCE는 Fed 공식 inflation 타겟. CPI보다 정책 결정 anchor로서 우월. 둘 다 노출.
    """
    yoy = _annualized(cpi, 12)
    core_yoy = _annualized(core_cpi, 12)
    m3 = _annualized(cpi, 3)
    m6 = _annualized(cpi, 6)
    accelerating = m3 > m6 > yoy

    # PCE는 optional input. 2026-05 fix: 결측 시 None (이전 0.0 → "PCE=0%" 와
    # 데이터 부재 가 동일하게 LLM 에 들어가 디플레/결측 구분 불가능했음).
    pce_yoy = _annualized(pce, 12) if pce is not None and len(pce) > 0 else None
    core_pce_yoy = _annualized(core_pce, 12) if core_pce is not None and len(core_pce) > 0 else None
    pce_m3 = _annualized(core_pce, 3) if core_pce is not None and len(core_pce) > 0 else None

    return InflationSnapshot(
        cpi_yoy=yoy,
        core_cpi_yoy=core_yoy,
        momentum_3mo=m3,
        momentum_6mo=m6,
        accelerating=accelerating,
        pce_yoy=pce_yoy,
        core_pce_yoy=core_pce_yoy,
        pce_momentum_3mo=pce_m3,
        source_date=as_of,
    )
