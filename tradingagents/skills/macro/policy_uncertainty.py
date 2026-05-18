from datetime import date

import pandas as pd

from tradingagents.schemas.macro import PolicyUncertaintySnapshot
from tradingagents.skills.registry import register_skill


# Baker-Bloom-Davis 가이드. 100 = 1985-2010 평균.
ELEVATED_THRESHOLD = 150.0
EXTREME_THRESHOLD = 200.0


def _classify_regime(us_epu: float) -> str:
    if us_epu >= EXTREME_THRESHOLD:
        return "extreme"
    if us_epu >= ELEVATED_THRESHOLD:
        return "elevated"
    return "normal"


@register_skill(name="compute_policy_uncertainty", category="macro")
def compute_policy_uncertainty(
    us_epu_series: pd.Series, global_epu_series: pd.Series, as_of: date,
) -> PolicyUncertaintySnapshot:
    """EPU 현재 level + 5년 percentile + 3-tier regime.

    EPU >150 (elevated) 구간은 평균 risk asset return이 유의하게 낮음 (Baker et al 2016).
    """
    us_current = float(us_epu_series.iloc[-1])
    global_current = float(global_epu_series.iloc[-1])

    # 5년 percentile (월간 → 60개)
    last_5y = us_epu_series.tail(60)
    percentile = float((last_5y < us_current).sum() / max(len(last_5y), 1))

    return PolicyUncertaintySnapshot(
        us_epu=us_current,
        global_epu=global_current,
        us_epu_percentile_5y=percentile,
        regime=_classify_regime(us_current),
        source_date=as_of,
    )
