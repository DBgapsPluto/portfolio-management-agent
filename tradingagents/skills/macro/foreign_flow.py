from datetime import date

import pandas as pd

from tradingagents.schemas.macro import ForeignFlowSnapshot
from tradingagents.skills.registry import register_skill


# 1y rolling 20일 누적 순매수 percentile 기반 (2026-05 fix).
# 이전 절대 임계 ±1조 KRW는 KOSPI 시총(~2500조) 대비 0.04%로 거의 일상 변동
# 수준이라 signal이 매번 발동했음. percentile 기반은 시총 변화에 자동 적응.
NET_BUYING_PERCENTILE = 0.80      # 1y 상위 20%면 net_buying
NET_SELLING_PERCENTILE = 0.20     # 1y 하위 20%면 net_selling


def _classify_signal_percentile(percentile_1y: float) -> str:
    if percentile_1y >= NET_BUYING_PERCENTILE:
        return "net_buying"
    if percentile_1y <= NET_SELLING_PERCENTILE:
        return "net_selling"
    return "neutral"


@register_skill(name="compute_foreign_flow", category="macro")
def compute_foreign_flow(
    foreign_daily_net: pd.Series, as_of: date,
) -> ForeignFlowSnapshot:
    """외국인 KOSPI 일별 순매수 → 5일/20일 누적 + 1y percentile-based signal.

    빈 series가 들어오면 sentinel.
    """
    if foreign_daily_net is None or foreign_daily_net.empty:
        return ForeignFlowSnapshot(
            net_5d_krw=0.0, net_20d_krw=0.0, signal="neutral",
            source_date=as_of, staleness_days=99,
        )

    net_5d = float(foreign_daily_net.tail(5).sum())
    net_20d = float(foreign_daily_net.tail(20).sum())

    # 1y rolling 20-day sums distribution
    rolling_20d = foreign_daily_net.rolling(20).sum().dropna()
    last_1y = rolling_20d.tail(252)
    if len(last_1y) >= 30 and float(last_1y.std()) > 0:
        percentile = float((last_1y < net_20d).sum() / len(last_1y))
        signal = _classify_signal_percentile(percentile)
    else:
        # 데이터 부족 또는 변동이 0이면 neutral.
        signal = "neutral"

    return ForeignFlowSnapshot(
        net_5d_krw=net_5d,
        net_20d_krw=net_20d,
        signal=signal,
        source_date=as_of,
    )
