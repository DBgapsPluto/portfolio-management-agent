from datetime import date, timedelta
from typing import Literal

from tradingagents.dataflows.volatility import fetch_vix, fetch_vkospi
from tradingagents.schemas.risk import VolatilitySnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_volatility_index", category="risk")
def fetch_volatility_index(
    index_name: Literal["VIX", "VKOSPI"], as_of: date,
) -> VolatilitySnapshot:
    start = as_of - timedelta(days=400)  # need ~250 days for percentile + 30 for z
    if index_name == "VIX":
        s = fetch_vix(start, as_of)
    else:
        s = fetch_vkospi(start, as_of)
    s = s.dropna()
    if s.empty:
        raise ValueError(f"No data for {index_name}")

    current = float(s.iloc[-1])
    last_30 = s.tail(30)
    z = (current - last_30.mean()) / last_30.std() if last_30.std() > 0 else 0.0
    last_5y = s.tail(252 * 5) if len(s) >= 252 else s
    pct = float((last_5y < current).sum() / len(last_5y))

    return VolatilitySnapshot(
        index_name=index_name,
        current_value=current,
        zscore_30d=float(z),
        percentile_5y=pct,
        source_date=as_of,
    )
