import logging
from datetime import date, timedelta
from typing import Literal

from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.schemas.risk import SpreadSnapshot
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


def _sentinel_credit_spread(region: str, as_of: date) -> SpreadSnapshot:
    """Backtest fix (2026-05-26): empty Series 시 raise 대신 sentinel 반환.

    FRED BAMLC0A0CM (us_ig_oas) 는 2023-05-23 이후 데이터만 → 2022/2023 초 시점
    backtest 시 raise ValueError 로 pipeline 죽임. Stage 1 audit 의 sentinel
    pattern (staleness_days=99) 과 일치하도록 sentinel 반환 → systemic_score
    합성이 graceful degrade.
    """
    return SpreadSnapshot(
        region=region, current_bps=100.0,   # neutral IG OAS placeholder (~1%)
        percentile_5y=0.5, widening=False, momentum_zscore=0.0,
        source_date=as_of, staleness_days=99,
    )


@register_skill(name="fetch_credit_spread", category="risk")
def fetch_credit_spread(
    region: Literal["US_IG", "US_HY"], as_of: date, api_key: str | None = None,
) -> SpreadSnapshot:
    series_id = "us_ig_oas" if region == "US_IG" else "us_hy_oas"
    start = as_of - timedelta(days=365 * 5 + 10)
    s = fetch_fred_series(series_id, start, as_of, api_key=api_key).dropna()
    if s.empty:
        # Backtest fix (2026-05-26): historical 시점에 series 미존재 가능 → sentinel.
        logger.warning(
            "fetch_credit_spread: no data for %s at as_of=%s (likely historical "
            "data unavailable, e.g., BAMLC0A0CM starts 2023-05-23) → sentinel",
            region, as_of,
        )
        return _sentinel_credit_spread(region, as_of)

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
