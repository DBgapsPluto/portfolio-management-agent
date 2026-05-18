from datetime import date

import pandas as pd

from tradingagents.schemas.risk import RealYieldsSnapshot
from tradingagents.skills.registry import register_skill


# TIPS 10y 임계 (학문/시장 컨센서스):
# < 0%      = accommodative (자산 가격 우호, 위험자산 매수 유인)
# 0 ~ 1%    = neutral
# 1 ~ 2%    = tight (자산 가격 압박 시작)
# > 2%      = very_tight (역사적으로 위험자산 매도 트리거)
ACCOMMODATIVE_THRESHOLD = 0.0
NEUTRAL_UPPER = 1.0
TIGHT_UPPER = 2.0


def _classify_regime(tips_10y: float) -> str:
    if tips_10y < ACCOMMODATIVE_THRESHOLD:
        return "accommodative"
    if tips_10y < NEUTRAL_UPPER:
        return "neutral"
    if tips_10y < TIGHT_UPPER:
        return "tight"
    return "very_tight"


@register_skill(name="compute_real_yields", category="risk")
def compute_real_yields(
    tips_10y_series: pd.Series, tips_5y_series: pd.Series, as_of: date,
) -> RealYieldsSnapshot:
    """TIPS 10y/5y → 실질 성장 기대치 진단.

    10y 실질금리는 자산 가격 결정에 가장 직접적 영향. 2022-2023 미국 주식 약세의
    핵심 driver였음 (real yield -1% → +2% 급등).
    """
    if tips_10y_series is None or tips_10y_series.empty:
        return RealYieldsSnapshot(
            tips_10y=0.0, tips_5y=0.0, spread_10y_5y=0.0, regime="neutral",
            source_date=as_of, staleness_days=99,
        )

    tips_10y = float(tips_10y_series.iloc[-1])
    tips_5y = float(tips_5y_series.iloc[-1]) if not tips_5y_series.empty else tips_10y
    spread = tips_10y - tips_5y

    return RealYieldsSnapshot(
        tips_10y=tips_10y,
        tips_5y=tips_5y,
        spread_10y_5y=spread,
        regime=_classify_regime(tips_10y),
        source_date=as_of,
    )
