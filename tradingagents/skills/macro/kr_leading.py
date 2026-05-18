from datetime import date

import pandas as pd

from tradingagents.schemas.macro import KRLeadingIndexSnapshot
from tradingagents.skills.registry import register_skill


def _phase(level: float, change_3mo: float) -> str:
    """CLI 순환변동치는 100 기준선. (level, 모멘텀) 4사분면으로 phase 결정."""
    above_trend = level >= 100.0
    rising = change_3mo > 0
    if above_trend and rising:
        return "expansion"
    if above_trend and not rising:
        return "peak"
    if not above_trend and not rising:
        return "contraction"
    return "trough"


@register_skill(name="compute_kr_leading_index", category="macro")
def compute_kr_leading_index(cli_series: pd.Series, as_of: date) -> KRLeadingIndexSnapshot:
    """선행지수 순환변동치 → level + 3/6개월 변화 + cycle phase 분류."""
    current = float(cli_series.iloc[-1])
    change_3mo = float(cli_series.iloc[-1] - cli_series.iloc[-4]) if len(cli_series) >= 4 else 0.0
    change_6mo = float(cli_series.iloc[-1] - cli_series.iloc[-7]) if len(cli_series) >= 7 else 0.0

    return KRLeadingIndexSnapshot(
        cli_value=current,
        change_3mo=change_3mo,
        change_6mo=change_6mo,
        phase=_phase(current, change_3mo),
        source_date=as_of,
    )
