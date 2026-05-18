from datetime import date

import pandas as pd

from tradingagents.schemas.macro import TailRiskSnapshot
from tradingagents.skills.registry import register_skill


def _percentile_1y(series: pd.Series, current: float) -> float:
    last_1y = series.tail(252)
    if len(last_1y) == 0:
        return 0.5
    return float((last_1y < current).sum() / len(last_1y))


def _classify_signal(vvix_pct: float, move_pct: float) -> str:
    """둘 다 90th percentile = extreme. 둘 중 하나 75th = elevated. 둘 다 정상 = calm."""
    if vvix_pct > 0.9 and move_pct > 0.9:
        return "extreme"
    if vvix_pct > 0.75 or move_pct > 0.75:
        return "elevated"
    return "calm"


@register_skill(name="compute_tail_risk", category="macro")
def compute_tail_risk(
    vvix_series: pd.Series, move_series: pd.Series, as_of: date,
) -> TailRiskSnapshot:
    """VVIX(vol-of-equity-vol) + MOVE(Treasury vol) 동시 추적.

    동시 급등 = 옵션 시장이 인지하는 tail event 가능성 상승.
    GPR(Caldara-Iacoviello)의 operational substitute.
    """
    vvix_current = float(vvix_series.iloc[-1])
    move_current = float(move_series.iloc[-1])

    vvix_pct = _percentile_1y(vvix_series, vvix_current)
    move_pct = _percentile_1y(move_series, move_current)

    return TailRiskSnapshot(
        vvix=vvix_current,
        move=move_current,
        vvix_percentile_1y=vvix_pct,
        move_percentile_1y=move_pct,
        signal=_classify_signal(vvix_pct, move_pct),
        source_date=as_of,
    )
