from datetime import date

import pandas as pd

from tradingagents.schemas.macro import ChinaLeadingSnapshot
from tradingagents.skills.registry import register_skill


def _phase(level: float, change_3mo: float) -> str:
    """OECD CLI 표준 해석. 100 = trend, (level, 모멘텀) 4사분면."""
    above_trend = level >= 100.0
    rising = change_3mo > 0
    if above_trend and rising:
        return "expansion"
    if above_trend and not rising:
        return "peak"
    if not above_trend and not rising:
        return "contraction"
    return "trough"


@register_skill(name="compute_china_leading", category="macro")
def compute_china_leading(cli_series: pd.Series, as_of: date) -> ChinaLeadingSnapshot:
    """OECD China amplitude-adjusted CLI → phase 분류.

    KR 수출의 25%가 중국이라 KR ETF 결정에 직접 transmission.
    """
    current = float(cli_series.iloc[-1])
    change_3mo = float(cli_series.iloc[-1] - cli_series.iloc[-4]) if len(cli_series) >= 4 else 0.0

    return ChinaLeadingSnapshot(
        cli_value=current,
        change_3mo=change_3mo,
        phase=_phase(current, change_3mo),
        source_date=as_of,
    )
