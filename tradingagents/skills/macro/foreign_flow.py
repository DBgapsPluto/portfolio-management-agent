from datetime import date

import pandas as pd

from tradingagents.schemas.macro import ForeignFlowSnapshot
from tradingagents.skills.registry import register_skill


# 임계치 (KRW). KOSPI 시총 대비 의미있는 flow 단위.
NET_BUYING_THRESHOLD = 1_000_000_000_000     # 1조 원 (20거래일 누적)
NET_SELLING_THRESHOLD = -1_000_000_000_000


def _classify_signal(net_20d: float) -> str:
    if net_20d > NET_BUYING_THRESHOLD:
        return "net_buying"
    if net_20d < NET_SELLING_THRESHOLD:
        return "net_selling"
    return "neutral"


@register_skill(name="compute_foreign_flow", category="macro")
def compute_foreign_flow(
    foreign_daily_net: pd.Series, as_of: date,
) -> ForeignFlowSnapshot:
    """외국인 KOSPI 일별 순매수 → 5일/20일 누적 + 시그널.

    빈 series가 들어오면 sentinel.
    """
    if foreign_daily_net is None or foreign_daily_net.empty:
        return ForeignFlowSnapshot(
            net_5d_krw=0.0, net_20d_krw=0.0, signal="neutral",
            source_date=as_of, staleness_days=99,
        )

    net_5d = float(foreign_daily_net.tail(5).sum())
    net_20d = float(foreign_daily_net.tail(20).sum())

    return ForeignFlowSnapshot(
        net_5d_krw=net_5d,
        net_20d_krw=net_20d,
        signal=_classify_signal(net_20d),
        source_date=as_of,
    )
