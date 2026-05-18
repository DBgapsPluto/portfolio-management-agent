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

    # Momentum z-score: 60일 일별 변화의 표준화된 강도
    # 양수 = 가속 widening (위기 진행 중), 음수 = 가속 tightening
    diffs = s.diff().dropna().tail(60) * 100  # 일별 변화량 (bps)
    if len(diffs) >= 5 and diffs.std() > 0:
        momentum_z = float(diffs.mean() / diffs.std())
    else:
        momentum_z = 0.0

    return SpreadSnapshot(
        region=region, current_bps=current, percentile_5y=pct,
        widening=widening, momentum_zscore=momentum_z,
        source_date=as_of,
    )
