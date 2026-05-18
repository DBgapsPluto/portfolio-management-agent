from datetime import date

import pandas as pd

from tradingagents.schemas.risk import KRYieldCurveSnapshot
from tradingagents.skills.registry import register_skill


# (10y - 3y) spread bps 임계
# > +50 bps  = normal (정상 우상향)
# -10 ~ +50  = flat (전환 구간)
# < -10 bps  = inverted (역전 신호, 침체 우려)
NORMAL_BPS = 50.0
INVERTED_BPS = -10.0


def _classify_regime(spread_bps: float) -> str:
    if spread_bps > NORMAL_BPS:
        return "normal"
    if spread_bps < INVERTED_BPS:
        return "inverted"
    return "flat"


@register_skill(name="compute_kr_yield_curve", category="risk")
def compute_kr_yield_curve(
    treasury_3y: pd.Series, treasury_10y: pd.Series, as_of: date,
) -> KRYieldCurveSnapshot:
    """한국 국고채 yield curve 진단. 미국과 별도 사이클 가능 (BOK vs Fed 정책차)."""
    if treasury_3y is None or treasury_3y.empty or treasury_10y.empty:
        return KRYieldCurveSnapshot(
            treasury_3y=0.0, treasury_10y=0.0, spread_10y_3y_bps=0.0,
            inverted=False, regime="flat",
            source_date=as_of, staleness_days=99,
        )

    y3 = float(treasury_3y.iloc[-1])
    y10 = float(treasury_10y.iloc[-1])
    spread_bps = (y10 - y3) * 100

    return KRYieldCurveSnapshot(
        treasury_3y=y3,
        treasury_10y=y10,
        spread_10y_3y_bps=spread_bps,
        inverted=spread_bps < 0,
        regime=_classify_regime(spread_bps),
        source_date=as_of,
    )
