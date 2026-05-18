from datetime import date

import pandas as pd

from tradingagents.schemas.macro import USLeadingIndexSnapshot
from tradingagents.skills.registry import register_skill


# Chicago Fed 공식 임계: 3-month MA < -0.7 → recession 진입 신호 (1967년 이후 검증)
RECESSION_THRESHOLD = -0.7


@register_skill(name="compute_us_leading_index", category="macro")
def compute_us_leading_index(
    cfnai: pd.Series, cfnai_ma3: pd.Series, as_of: date,
) -> USLeadingIndexSnapshot:
    """CFNAI(Chicago Fed National Activity Index) 스냅샷.

    85개 매크로 지표 합성. 0 = trend 성장, 음수 = below trend.
    CFNAIMA3 < -0.7 = recession 진입 (학문적으로 검증된 단일 임계).
    """
    current = float(cfnai.iloc[-1])
    ma3 = float(cfnai_ma3.iloc[-1])
    recession = ma3 < RECESSION_THRESHOLD

    return USLeadingIndexSnapshot(
        cfnai_value=current,
        cfnai_ma3=ma3,
        recession_signal=recession,
        source_date=as_of,
    )
