from datetime import date

import pandas as pd

from tradingagents.schemas.macro import GDPNowSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_gdp_nowcast", category="macro")
def compute_gdp_nowcast(gdpnow: pd.Series, as_of: date) -> GDPNowSnapshot:
    """Atlanta Fed GDPNow 스냅샷. 주 2회 갱신되는 실시간 분기 GDP nowcast."""
    current = float(gdpnow.iloc[-1])
    change = float(gdpnow.iloc[-1] - gdpnow.iloc[-2]) if len(gdpnow) >= 2 else 0.0

    return GDPNowSnapshot(
        nowcast_pct=current,
        change_from_prior=change,
        source_date=as_of,
    )
