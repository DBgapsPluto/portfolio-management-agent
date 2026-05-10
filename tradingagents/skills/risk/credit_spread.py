from datetime import date, timedelta
from typing import Literal

from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.schemas.risk import SpreadSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_credit_spread", category="risk")
def fetch_credit_spread(
    region: Literal["US_IG", "US_HY"], as_of: date, api_key: str | None = None,
) -> SpreadSnapshot:
    series_id = "us_ig_oas" if region == "US_IG" else "us_hy_oas"
    start = as_of - timedelta(days=365 * 5 + 10)
    s = fetch_fred_series(series_id, start, as_of, api_key=api_key).dropna()
    if s.empty:
        raise ValueError(f"No data for {region}")

    current = float(s.iloc[-1]) * 100  # FRED OAS in % → bps
    last_5y = s.tail(252 * 5) * 100
    pct = float((last_5y < current).sum() / len(last_5y))
    widening = bool(s.tail(20).mean() > s.tail(60).mean())

    return SpreadSnapshot(
        region=region, current_bps=current, percentile_5y=pct,
        widening=widening, source_date=as_of,
    )
