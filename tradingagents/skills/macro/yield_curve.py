import logging
from datetime import date

import pandas as pd

from tradingagents.schemas.macro import YieldCurveSnapshot
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


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


# 2026-05-23 C4 — long-end slope (5-30y) for factor model F4 term_premium.
# 기존 compute_yield_curve 는 10y-2y / 10y-3m (단기-중기 정책 기대).
# 5-30y 는 별개 — long-end real economy term premium signal. C3 의 5 indicator
# pattern (D7/D8/D9) 동일 적용 — scalar return + analyst .model_copy(update=...).
@register_skill(name="compute_yield_curve_extras", category="macro")
def compute_yield_curve_extras(
    dgs5_pct: float | None,
    dgs30_pct: float | None,
    as_of: date,
) -> float | None:
    """Returns 5-30y slope in basis points (DGS30 - DGS5) * 100.

    Args:
        dgs5_pct: 5y Treasury yield in percent.
        dgs30_pct: 30y Treasury yield in percent.
        as_of: report as-of date (advisory — series itself is point-in-time).

    Returns:
        Spread in bps on success, or None if either input is None (D8 graceful).

    Notes:
        - D7: scalar return — analyst applies yc.model_copy(update={"spread_30y_5y_bps": ...}).
        - D8: None on missing input + logger.warning. No default fill, no raise.
        - D9: no retry / no cache inside skill.
    """
    try:
        if dgs5_pct is None or dgs30_pct is None:
            logger.warning(
                "slope_5_30y inputs missing (dgs5=%s, dgs30=%s, as_of=%s) — F4 term_premium component skipped",
                dgs5_pct, dgs30_pct, as_of,
            )
            return None
        return (float(dgs30_pct) - float(dgs5_pct)) * 100.0
    except Exception as e:
        logger.warning("slope_5_30y compute failed (as_of=%s): %s", as_of, e)
        return None
