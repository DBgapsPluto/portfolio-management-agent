from datetime import date

import pandas as pd

from tradingagents.schemas.risk import SkewSnapshot
from tradingagents.skills.registry import register_skill


# CBOE SKEW 임계 (역사 평균 ~118)
# < 120: low (외가격 풋 헷지 수요 낮음, 시장이 정규분포 가정)
# 120 ~ 130: normal
# 130 ~ 145: elevated (외가격 풋 가격 책정 — black swan 우려 상승)
# > 145: extreme (극단적 tail hedge 수요)
SKEW_LOW = 120.0
SKEW_NORMAL = 130.0
SKEW_ELEVATED = 145.0


def _classify_signal(skew_value: float) -> str:
    if skew_value < SKEW_LOW:
        return "low"
    if skew_value < SKEW_NORMAL:
        return "normal"
    if skew_value < SKEW_ELEVATED:
        return "elevated"
    return "extreme"


@register_skill(name="compute_skew_index", category="risk")
def compute_skew_index(skew_series: pd.Series, as_of: date) -> SkewSnapshot:
    """CBOE SKEW Index → 외가격 풋 헷지 수요 정량화.

    SKEW > VIX 신호와 함께 발생 시 가장 강력 (위험 인지 + 가격 책정 동시).
    """
    if skew_series is None or skew_series.empty:
        return SkewSnapshot(
            skew_value=118.0, percentile_1y=0.5, tail_hedge_signal="normal",
            source_date=as_of, staleness_days=99,
        )

    current = float(skew_series.iloc[-1])
    last_1y = skew_series.tail(252)
    percentile = float((last_1y < current).sum() / max(len(last_1y), 1))

    return SkewSnapshot(
        skew_value=current,
        percentile_1y=percentile,
        tail_hedge_signal=_classify_signal(current),
        source_date=as_of,
    )
