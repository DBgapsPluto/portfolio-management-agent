from datetime import date

import pandas as pd

from tradingagents.schemas.risk import SkewSnapshot
from tradingagents.skills.registry import register_skill


# 1y percentile-based regime (2026-05 fix).
# 이전: 절대 임계 120/130/145 (역사 평균 118 기준) — 2020+ SKEW 평균이 이미
# ~145라 "extreme"이 일상이 됐음. percentile 기반은 base shift 자동 적응.
LOW_PCT = 0.25       # 1y 하위 25%
NORMAL_PCT = 0.50    # 1y 중앙 25-50%
ELEVATED_PCT = 0.85  # 1y 상위 15%


def _classify_signal(percentile_1y: float) -> str:
    if percentile_1y < LOW_PCT:
        return "low"
    if percentile_1y < NORMAL_PCT:
        return "normal"
    if percentile_1y < ELEVATED_PCT:
        return "elevated"
    return "extreme"


@register_skill(name="compute_skew_index", category="risk")
def compute_skew_index(skew_series: pd.Series, as_of: date) -> SkewSnapshot:
    """CBOE SKEW Index → 외가격 풋 헷지 수요 정량화 (percentile-based regime).

    SKEW 1y 상위 15%가 "extreme" tail hedge 수요. VIX 동반 상승 시 가장 강력
    (위험 인지 + 가격 책정 동시).
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
        tail_hedge_signal=_classify_signal(percentile),
        source_date=as_of,
    )
