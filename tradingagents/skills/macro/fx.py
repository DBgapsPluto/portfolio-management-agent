from datetime import date

import pandas as pd

from tradingagents.schemas.macro import FXSnapshot
from tradingagents.skills.registry import register_skill


def _pct_change_1m(series: pd.Series) -> float:
    """약 1개월(=21 거래일) 전 대비 % 변화."""
    if len(series) < 22:
        return 0.0
    return float((series.iloc[-1] / series.iloc[-22] - 1) * 100)


def _classify_regime(krw_change: float, dxy_change: float) -> str:
    """KRW/DXY 동조성으로 regime 판별.

    krw_change > +2 AND dxy_change > +1   → usd_risk_off (USD 강세 + KRW 약세 동시 = 외국인 매도)
    krw_change > +2                       → krw_weak
    krw_change < -2                       → krw_strong
    else                                  → neutral
    """
    if krw_change > 2.0 and dxy_change > 1.0:
        return "usd_risk_off"
    if krw_change > 2.0:
        return "krw_weak"
    if krw_change < -2.0:
        return "krw_strong"
    return "neutral"


@register_skill(name="compute_fx_overlay", category="macro")
def compute_fx_overlay(
    usd_krw: pd.Series, dxy: pd.Series, as_of: date,
) -> FXSnapshot:
    """USD/KRW + DXY → KRW 강도 + 글로벌 USD 강도 동시 진단."""
    krw_change = _pct_change_1m(usd_krw)
    dxy_change = _pct_change_1m(dxy)

    return FXSnapshot(
        usd_krw=float(usd_krw.iloc[-1]),
        dxy=float(dxy.iloc[-1]),
        krw_change_1m_pct=krw_change,
        dxy_change_1m_pct=dxy_change,
        regime=_classify_regime(krw_change, dxy_change),
        source_date=as_of,
    )
