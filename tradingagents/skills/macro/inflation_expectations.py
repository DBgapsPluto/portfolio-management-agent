from datetime import date

import pandas as pd

from tradingagents.schemas.macro import InflationExpectationsSnapshot
from tradingagents.skills.registry import register_skill


# 학문/Fed 가이드 임계. anchored = Fed 2% 타깃 부근 ±α 범위.
#
# ⚠️ HARDCODED CAVEAT (#7, 2026-05 audit):
#   임계 (breakeven 1.5~3.0, michigan 2.0~4.0)는 **Fed 2% 타겟 + 학술 컨센서스**
#   에 기반. Fed가 2% 타겟을 변경하면 (e.g. 2.5% target — 일부 논의 있음) 모두
#   stale. Michigan은 retail survey라 systematic bias (가계가 일관되게 Fed보다
#   높게 답함) 때문에 4% 까지 normal로 본 것.
#   타겟 변경 시 update 필요. 2026-05 현재 Fed 2% 유효.
BREAKEVEN_ANCHOR_LOW = 1.5
BREAKEVEN_ANCHOR_HIGH = 3.0
MICHIGAN_ANCHOR_LOW = 2.0
MICHIGAN_ANCHOR_HIGH = 4.0


def _classify_unanchored(breakeven: float, michigan: float) -> str:
    if breakeven > BREAKEVEN_ANCHOR_HIGH or michigan > MICHIGAN_ANCHOR_HIGH:
        return "upside"
    if breakeven < BREAKEVEN_ANCHOR_LOW:
        return "downside"
    return "none"


@register_skill(name="compute_inflation_expectations", category="macro")
def compute_inflation_expectations(
    breakeven_5y5y_series: pd.Series, michigan_1y_series: pd.Series, as_of: date,
) -> InflationExpectationsSnapshot:
    """5Y5Y forward breakeven (시장 기반, 장기) + Michigan 1y (서베이, 단기).

    두 시그널의 동시 anchor 여부가 핵심 — 시장과 가계 기대가 일치할 때만 anchored.
    """
    breakeven = float(breakeven_5y5y_series.iloc[-1])
    michigan = float(michigan_1y_series.iloc[-1])

    breakeven_anchored = BREAKEVEN_ANCHOR_LOW <= breakeven <= BREAKEVEN_ANCHOR_HIGH
    michigan_anchored = MICHIGAN_ANCHOR_LOW <= michigan <= MICHIGAN_ANCHOR_HIGH

    return InflationExpectationsSnapshot(
        breakeven_5y5y=breakeven,
        michigan_1y=michigan,
        anchored=breakeven_anchored and michigan_anchored,
        unanchored_direction=_classify_unanchored(breakeven, michigan),
        source_date=as_of,
    )
