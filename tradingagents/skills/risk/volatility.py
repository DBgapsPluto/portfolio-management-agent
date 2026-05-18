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
        # D5 tier-3 degradation — emit a stale-marked sentinel so downstream
        # market_risk_analyst can keep working (esp. VKOSPI when KRX login fails).
        return VolatilitySnapshot(
            index_name=index_name,
            current_value=0.0, zscore_30d=0.0, percentile_5y=0.5,
            source_date=as_of, staleness_days=99,
        )

    current = float(s.iloc[-1])
    last_30 = s.tail(30)
    z = (current - last_30.mean()) / last_30.std() if last_30.std() > 0 else 0.0
    last_5y = s.tail(252 * 5) if len(s) >= 252 else s
    pct = float((last_5y < current).sum() / len(last_5y))
    # 4-week 절대 변화 (≈20 거래일). 추세 방향 capture.
    change_4w = float(s.iloc[-1] - s.iloc[-21]) if len(s) >= 21 else 0.0

    return VolatilitySnapshot(
        index_name=index_name,
        current_value=current,
        zscore_30d=float(z),
        percentile_5y=pct,
        change_4w=change_4w,
        source_date=as_of,
    )
