from datetime import date

import pandas as pd

from tradingagents.schemas.macro import PolicyUncertaintySnapshot
from tradingagents.skills.registry import register_skill


# 5y percentile-based regime (2026-05 fix).
# 이전: 절대 임계 150/200 (BBD 2016) — 2020+ EPU 평균이 이미 ~180이라 거의 항상
# "elevated"로 떨어져 정보 가치 0이었음. percentile 기반은 시기적 base shift에
# 자동 적응.
ELEVATED_PCT = 0.70   # 5y 상위 30%
EXTREME_PCT = 0.90    # 5y 상위 10%


def _classify_regime(percentile_5y: float) -> str:
    if percentile_5y >= EXTREME_PCT:
        return "extreme"
    if percentile_5y >= ELEVATED_PCT:
        return "elevated"
    return "normal"


@register_skill(name="compute_policy_uncertainty", category="macro")
def compute_policy_uncertainty(
    us_epu_series: pd.Series, global_epu_series: pd.Series, as_of: date,
) -> PolicyUncertaintySnapshot:
    """EPU 현재 level + 5년 percentile + 3-tier regime (percentile-based).

    EPU 상위 30% 구간은 평균 risk asset return이 유의하게 낮음 (Baker et al
    2016). 절대 level 임계는 2020+ shifted base 때문에 폐기 (위 주석 참고).
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
        regime=_classify_regime(percentile),
        source_date=as_of,
    )
