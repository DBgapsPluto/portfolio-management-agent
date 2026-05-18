from datetime import date

import pandas as pd

from tradingagents.schemas.macro import KRBusinessSurveySnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_kr_business_survey", category="macro")
def compute_kr_business_survey(
    bsi_mfg: pd.Series, as_of: date,
) -> KRBusinessSurveySnapshot:
    """BOK 제조업 업황 BSI 스냅샷.

    BSI는 100 기준선. 100 미만 = 부정적 응답이 다수. 80 미만 = 명확한 위축 국면.
    """
    current = float(bsi_mfg.iloc[-1])
    change_3mo = float(bsi_mfg.iloc[-1] - bsi_mfg.iloc[-4]) if len(bsi_mfg) >= 4 else 0.0
    contraction = current < 80.0

    return KRBusinessSurveySnapshot(
        mfg_bsi=current,
        change_3mo=change_3mo,
        contraction_signal=contraction,
        source_date=as_of,
    )
