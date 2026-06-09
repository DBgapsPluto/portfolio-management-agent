from datetime import date

import pandas as pd

from tradingagents.schemas.technical import SemiMomentumSnapshot
from tradingagents.skills.registry import register_skill


def _ret(s: pd.Series | None, days: int) -> float:
    if s is None or len(s) <= days:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - days] - 1) * 100


@register_skill(name="compute_semi_momentum", category="technical")
def compute_semi_momentum(
    sox: pd.Series, smh: pd.Series, spy: pd.Series, as_of: date,
) -> SemiMomentumSnapshot:
    """^SOX/SMH 모멘텀 + SPY 대비 상대강도 + 미·글로벌 디버전스."""
    if sox is None or sox.empty:
        return SemiMomentumSnapshot(
            sox_ret_3m_pct=0.0, sox_ret_6m_pct=0.0, smh_ret_3m_pct=0.0,
            smh_vs_spy_rel_3m=0.0, sox_minus_smh_div_3m=0.0,
            source_date=as_of, staleness_days=99,
        )
    sox_3m = _ret(sox, 63)
    smh_3m = _ret(smh, 63)
    spy_3m = _ret(spy, 63)
    return SemiMomentumSnapshot(
        sox_ret_3m_pct=sox_3m,
        sox_ret_6m_pct=_ret(sox, 126),
        smh_ret_3m_pct=smh_3m,
        smh_vs_spy_rel_3m=smh_3m - spy_3m,
        sox_minus_smh_div_3m=sox_3m - smh_3m,
        source_date=as_of,
    )
