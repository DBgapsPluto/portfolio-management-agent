from datetime import date

import pandas as pd

from tradingagents.schemas.risk import VIXTermStructureSnapshot
from tradingagents.skills.registry import register_skill


# 임계: ratio = vix_3m / vix_front
# > 1.05 = contango (정상 우상향, 시장 calm)
# 0.95 ~ 1.05 = flat (전환 구간)
# < 0.95 = backwardation (현재 stress 우선, 향후 진정 기대; 위기 신호)
CONTANGO_THRESHOLD = 1.05
BACKWARDATION_THRESHOLD = 0.95


def _classify_regime(ratio: float) -> str:
    if ratio > CONTANGO_THRESHOLD:
        return "contango"
    if ratio < BACKWARDATION_THRESHOLD:
        return "backwardation"
    return "flat"


@register_skill(name="compute_vix_term_structure", category="risk")
def compute_vix_term_structure(
    vix_front: pd.Series, vix_3m: pd.Series, as_of: date,
) -> VIXTermStructureSnapshot:
    """VIX front (spot) vs VXV (3-month forward) → 시장 stress 인식의 시간 구조.

    backwardation은 강력한 위기 신호 (2008, 2020 등 시장 panic 시 발생).
    """
    front = float(vix_front.iloc[-1])
    far = float(vix_3m.iloc[-1])
    if front <= 0:
        # 안전망 — division by zero 방지
        ratio = 1.0
    else:
        ratio = far / front

    return VIXTermStructureSnapshot(
        vix_front=front,
        vix_3m=far,
        ratio=ratio,
        regime=_classify_regime(ratio),
        source_date=as_of,
    )
