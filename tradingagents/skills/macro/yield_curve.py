from datetime import date

import pandas as pd

from tradingagents.schemas.macro import YieldCurveSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_yield_curve", category="macro")
def compute_yield_curve(
    s_10y: pd.Series,
    s_2y: pd.Series,
    s_3m: pd.Series,
    as_of: date,
) -> YieldCurveSnapshot:
    """Yield curve snapshot. Inputs are FRED-derived series.

    Spreads in basis points. inverted_days_count from last 365 days of overlap.
    """
    spread_10y_2y = float(s_10y.iloc[-1] - s_2y.iloc[-1]) * 100
    spread_10y_3m = float(s_10y.iloc[-1] - s_3m.iloc[-1]) * 100

    aligned = pd.concat([s_10y, s_2y], axis=1, join="inner").dropna()
    aligned.columns = ["10y", "2y"]
    aligned["spread"] = aligned["10y"] - aligned["2y"]
    last_365 = aligned.tail(365)
    inverted_days = int((last_365["spread"] < 0).sum())

    last_5y = aligned.tail(252 * 5) if len(aligned) >= 252 else aligned
    if len(last_5y) > 1:
        rank = (last_5y["spread"] < spread_10y_2y / 100).sum()
        percentile = float(rank / len(last_5y))
    else:
        percentile = 0.5

    return YieldCurveSnapshot(
        spread_10y_2y_bps=spread_10y_2y,
        spread_10y_3m_bps=spread_10y_3m,
        inverted_days_count=inverted_days,
        percentile_5y=percentile,
        source_date=as_of,
        staleness_days=0,
    )
