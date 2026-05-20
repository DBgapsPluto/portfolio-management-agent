from datetime import date

import pandas as pd

from tradingagents.schemas.risk import VxnSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_vxn", category="risk")
def compute_vxn(
    vxn_series: pd.Series, vix_series: pd.Series, as_of: date,
) -> VxnSnapshot:
    """CBOE NASDAQ-100 Volatility (VXN) 스냅샷.

    VXN > VIX = 기술주 stress가 broad market보다 큼.
    스프레드 > 5pt면 의미있는 편중 (예: AI 거품 우려, mega-cap 회전).
    """
    if vxn_series is None or vxn_series.empty:
        return VxnSnapshot(
            current_value=0.0, zscore_30d=0.0, percentile_5y=0.5,
            spread_vs_vix=0.0, source_date=as_of, staleness_days=99,
        )

    current = float(vxn_series.iloc[-1])
    last_30 = vxn_series.tail(30)
    z = (current - last_30.mean()) / last_30.std() if last_30.std() > 0 else 0.0
    last_5y = vxn_series.tail(252 * 5) if len(vxn_series) >= 252 else vxn_series
    pct = float((last_5y < current).sum() / max(len(last_5y), 1))

    vix_now = float(vix_series.iloc[-1]) if vix_series is not None and not vix_series.empty else 0.0
    spread = current - vix_now

    return VxnSnapshot(
        current_value=current,
        zscore_30d=float(z),
        percentile_5y=pct,
        spread_vs_vix=spread,
        tech_focused_stress=spread > 5.0,
        source_date=as_of,
    )
