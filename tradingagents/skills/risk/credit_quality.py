from datetime import date

import pandas as pd

from tradingagents.schemas.risk import CreditQualitySnapshot
from tradingagents.skills.registry import register_skill


# quality spread (BBB - AAA) percentile 임계
# < 0.5  = calm (정상 differential)
# 0.5~0.85 = elevated (BBB 추가 리스크 가산 시작)
# > 0.85 = stress (flight to quality 강함)
ELEVATED_PCT = 0.5
STRESS_PCT = 0.85


def _classify_regime(percentile: float) -> str:
    if percentile < ELEVATED_PCT:
        return "calm"
    if percentile < STRESS_PCT:
        return "elevated"
    return "stress"


@register_skill(name="compute_credit_quality", category="risk")
def compute_credit_quality(
    aaa_series: pd.Series, bbb_series: pd.Series, as_of: date,
) -> CreditQualitySnapshot:
    """AAA vs BBB OAS spread → 신용 등급간 quality differential.

    Quality spread 확대 = 시장이 BBB 추가 risk 가산. 위기 진입의 선행 신호.
    """
    if aaa_series is None or aaa_series.empty or bbb_series.empty:
        return CreditQualitySnapshot(
            aaa_oas_bps=0.0, bbb_oas_bps=0.0, quality_spread_bps=0.0,
            percentile_5y=0.5, regime="calm",
            source_date=as_of, staleness_days=99,
        )

    aaa_bps = float(aaa_series.iloc[-1]) * 100  # % → bps
    bbb_bps = float(bbb_series.iloc[-1]) * 100
    quality_spread = bbb_bps - aaa_bps

    # 5년 percentile: 일별 quality spread series 구성
    aligned = pd.concat([aaa_series, bbb_series], axis=1, join="inner").dropna()
    if len(aligned) < 20:
        percentile = 0.5  # 데이터 부족 시 중립
    else:
        aligned.columns = ["aaa", "bbb"]
        spread_series = (aligned["bbb"] - aligned["aaa"]) * 100
        last_5y = spread_series.tail(252 * 5)
        percentile = float((last_5y < quality_spread).sum() / max(len(last_5y), 1))

    return CreditQualitySnapshot(
        aaa_oas_bps=aaa_bps,
        bbb_oas_bps=bbb_bps,
        quality_spread_bps=quality_spread,
        percentile_5y=percentile,
        regime=_classify_regime(percentile),
        source_date=as_of,
    )
