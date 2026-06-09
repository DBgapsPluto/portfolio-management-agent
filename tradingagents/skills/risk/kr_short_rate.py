from datetime import date

import pandas as pd

from tradingagents.schemas.risk import KRShortRateSnapshot
from tradingagents.skills.registry import register_skill


def _classify_regime(spread_bps: float) -> str:
    if spread_bps > 0:
        return "stress"
    if spread_bps >= -20:   # -20 포함 (schema: "-20~0 elevated")
        return "elevated"
    return "calm"


@register_skill(name="compute_kr_short_rate", category="risk")
def compute_kr_short_rate(
    cd91: pd.Series, treasury_3y: pd.Series, as_of: date,
) -> KRShortRateSnapshot:
    """CD 91일 vs 국고채 3y → 단기 자금시장 funding stress."""
    if cd91 is None or cd91.empty:
        return KRShortRateSnapshot(
            cd91=0.0, cd91_minus_treasury3y_bps=0.0, regime="calm",
            source_date=as_of, staleness_days=99,
        )
    cd = float(cd91.iloc[-1])
    t3 = float(treasury_3y.iloc[-1]) if treasury_3y is not None and not treasury_3y.empty else cd
    spread_bps = (cd - t3) * 100
    return KRShortRateSnapshot(
        cd91=cd,
        cd91_minus_treasury3y_bps=spread_bps,
        regime=_classify_regime(spread_bps),
        source_date=as_of,
    )
