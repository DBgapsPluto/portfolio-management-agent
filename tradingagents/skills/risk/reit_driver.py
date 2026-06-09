from datetime import date

import pandas as pd

from tradingagents.schemas.risk import REITDriverSnapshot
from tradingagents.skills.registry import register_skill


def _ret(s: pd.Series | None, days: int) -> float:
    if s is None or len(s) <= days:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - days] - 1) * 100


def _last(s: pd.Series | None) -> float:
    return float(s.iloc[-1]) if s is not None and not s.empty else 0.0


@register_skill(name="compute_reit_driver", category="risk")
def compute_reit_driver(
    vnq: pd.Series, xlre: pd.Series, schh: pd.Series,
    mortgage: pd.Series, dgs10: pd.Series, as_of: date,
) -> REITDriverSnapshot:
    """US REIT 모멘텀·dispersion + 모기지 스프레드."""
    if vnq is None or vnq.empty:
        return REITDriverSnapshot(
            us_reit_ret_3m_pct=0.0, us_reit_ret_6m_pct=0.0,
            source_date=as_of, staleness_days=99,
        )
    rets_3m = [_ret(s, 63) for s in (vnq, xlre, schh) if s is not None and not s.empty]
    dispersion = float(pd.Series(rets_3m).std(ddof=0)) if len(rets_3m) >= 2 else 0.0
    mort = _last(mortgage)
    ten = _last(dgs10)
    spread_bps = (mort - ten) * 100 if (mort and ten) else 0.0
    return REITDriverSnapshot(
        us_reit_ret_3m_pct=_ret(vnq, 63),
        us_reit_ret_6m_pct=_ret(vnq, 126),
        us_reit_dispersion=dispersion,
        mortgage_30y=mort,
        mortgage_minus_10y_bps=spread_bps,
        regime="neutral",
        source_date=as_of,
    )
