from datetime import date

import pandas as pd

from tradingagents.schemas.macro import EmergingMarketSnapshot
from tradingagents.skills.registry import register_skill


def _ret(s: pd.Series | None, days: int) -> float:
    if s is None or len(s) <= days:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - days] - 1) * 100


def _classify(rel: float) -> str:
    if rel > 3:
        return "risk_on"
    if rel < -3:
        return "risk_off"
    return "neutral"


@register_skill(name="compute_emerging_market", category="macro")
def compute_emerging_market(
    eem: pd.Series, emb: pd.Series, dxy: pd.Series, as_of: date,
) -> EmergingMarketSnapshot:
    """EEM/EMB 모멘텀 + DXY 대비 상대강도."""
    if eem is None or eem.empty:
        return EmergingMarketSnapshot(
            em_equity_ret_3m_pct=0.0, em_equity_ret_6m_pct=0.0,
            em_debt_ret_3m_pct=0.0, em_vs_dxy_rel=0.0, regime="neutral",
            source_date=as_of, staleness_days=99,
        )
    eem_3m = _ret(eem, 63)
    dxy_3m = _ret(dxy, 63)
    rel = eem_3m - dxy_3m
    return EmergingMarketSnapshot(
        em_equity_ret_3m_pct=eem_3m, em_equity_ret_6m_pct=_ret(eem, 126),
        em_debt_ret_3m_pct=_ret(emb, 63), em_vs_dxy_rel=rel, regime=_classify(rel),
    )
