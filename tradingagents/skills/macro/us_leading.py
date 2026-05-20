from datetime import date
from typing import Literal

import pandas as pd

from tradingagents.schemas.macro import USLeadingIndexSnapshot
from tradingagents.skills.registry import register_skill


# Chicago Fed 공식 임계: 3-month MA < -0.7 → recession 진입 신호 (1967년 이후 검증)
RECESSION_THRESHOLD = -0.7
# ⚠️ HARDCODED CAVEAT (#3, 2026-05 audit):
#   -1.5 / -2.5 임계는 **우리 자의적 추가** (Chicago Fed 공식 아님).
#   참고로 historical:
#     - 1990 침체: CFNAIMA3 ~ -1.2 (mild)
#     - 2008 GFC : CFNAIMA3 < -2.5 (severe, 한때 -3.5)
#     - 2020 COVID: 일시적 -7+ (outlier, 1개월)
#     - 2024 false: -0.8 ~ -1.0 부근
#   3-tier 구분은 LLM에게 강도 hint 제공이 목적. 정밀 calibration 없음.
MODERATE_THRESHOLD = -1.5
SEVERE_THRESHOLD = -2.5


def _severity(ma3: float) -> Literal["none", "mild", "moderate", "severe"]:
    """2026-05 fix — 단일 임계 -0.7 만으론 strength 분간 못함 (COVID -7 vs 일반 -1)."""
    if ma3 >= RECESSION_THRESHOLD:
        return "none"
    if ma3 >= MODERATE_THRESHOLD:
        return "mild"
    if ma3 >= SEVERE_THRESHOLD:
        return "moderate"
    return "severe"


@register_skill(name="compute_us_leading_index", category="macro")
def compute_us_leading_index(
    cfnai: pd.Series, cfnai_ma3: pd.Series, as_of: date,
) -> USLeadingIndexSnapshot:
    """CFNAI(Chicago Fed National Activity Index) 스냅샷.

    85개 매크로 지표 합성. 0 = trend 성장, 음수 = below trend.
    CFNAIMA3 < -0.7 = recession 진입 (학문적으로 검증된 단일 임계).
    severity는 3-tier (mild/moderate/severe)로 강도 정보 보강.
    """
    current = float(cfnai.iloc[-1])
    ma3 = float(cfnai_ma3.iloc[-1])
    recession = ma3 < RECESSION_THRESHOLD

    return USLeadingIndexSnapshot(
        cfnai_value=current,
        cfnai_ma3=ma3,
        recession_signal=recession,
        recession_severity=_severity(ma3),
        source_date=as_of,
    )
