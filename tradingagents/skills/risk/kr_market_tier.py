from datetime import date

import pandas as pd

from tradingagents.schemas.risk import KRMarketTierSnapshot
from tradingagents.skills.registry import register_skill


# KOSDAQ - KOSPI 20일 수익률 격차 임계
# > +3% = small_cap_risk_on  (중소형 outperform, retail/growth 우호)
# -3% ~ +3% = neutral
# < -3% = large_cap_risk_off (대형주 outperform, flight-to-quality, 위기 신호)
RISK_ON_THRESHOLD = 3.0
RISK_OFF_THRESHOLD = -3.0


def _classify_signal(relative_perf: float) -> str:
    if relative_perf > RISK_ON_THRESHOLD:
        return "small_cap_risk_on"
    if relative_perf < RISK_OFF_THRESHOLD:
        return "large_cap_risk_off"
    return "neutral"


def _return_20d_pct(series: pd.Series) -> float:
    if len(series) < 21:
        return 0.0
    prior = float(series.iloc[-21])
    if prior <= 0:
        return 0.0
    return (float(series.iloc[-1]) / prior - 1) * 100


@register_skill(name="compute_kr_market_tier", category="risk")
def compute_kr_market_tier(
    kospi: pd.Series, kosdaq: pd.Series, as_of: date,
) -> KRMarketTierSnapshot:
    """KOSPI vs KOSDAQ 상대 성과 → KR 내부 risk on/off 분류.

    대형주 outperform 강함 = flight-to-quality, 중소형 outperform = retail risk-on.
    """
    if kospi is None or kospi.empty or kosdaq.empty:
        return KRMarketTierSnapshot(
            kospi_return_20d_pct=0.0, kosdaq_return_20d_pct=0.0,
            relative_perf_pct=0.0, signal="neutral",
            source_date=as_of, staleness_days=99,
        )

    kospi_ret = _return_20d_pct(kospi)
    kosdaq_ret = _return_20d_pct(kosdaq)
    relative = kosdaq_ret - kospi_ret

    return KRMarketTierSnapshot(
        kospi_return_20d_pct=kospi_ret,
        kosdaq_return_20d_pct=kosdaq_ret,
        relative_perf_pct=relative,
        signal=_classify_signal(relative),
        source_date=as_of,
    )
