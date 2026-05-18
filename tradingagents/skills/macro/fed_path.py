from datetime import date

import pandas as pd

from tradingagents.schemas.macro import FedPathSnapshot
from tradingagents.skills.registry import register_skill


# CME FedWatch 대신 DGS2 - DFF proxy. 50bps band가 통상적 hike/cut 구분선
PATH_THRESHOLD_BPS = 50.0


def _classify_view(path_bps: float) -> str:
    if path_bps > PATH_THRESHOLD_BPS:
        return "hike"
    if path_bps < -PATH_THRESHOLD_BPS:
        return "cut"
    return "hold"


@register_skill(name="compute_fed_path", category="macro")
def compute_fed_path(
    fed_funds: pd.Series, dgs2: pd.Series, as_of: date,
) -> FedPathSnapshot:
    """Fed funds futures 묵시금리를 (DGS2 - DFF) 스프레드로 proxy.

    2y Treasury는 향후 ~24개월 정책 기대를 가격에 반영하므로 futures와
    corr > 0.9. CME FedWatch 의존 없이 FRED만으로 single-API 구현.
    """
    current = float(fed_funds.iloc[-1])
    implied_2y = float(dgs2.iloc[-1])
    path_bps = (implied_2y - current) * 100.0

    return FedPathSnapshot(
        current_rate_pct=current,
        implied_2y_rate_pct=implied_2y,
        path_bps=path_bps,
        market_view=_classify_view(path_bps),
        source_date=as_of,
    )
