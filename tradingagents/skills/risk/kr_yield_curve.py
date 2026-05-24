from datetime import date
from typing import Literal

import pandas as pd

from tradingagents.schemas.risk import KRYieldCurveSnapshot
from tradingagents.skills.registry import register_skill


# 2026-05 percentile-based regime (BOK 정책 사이클 base shift 흡수).
# 5y percentile 기반 — KR 금리 레벨 자체가 사이클로 통째로 shift 하므로 절대
# 임계 +50/-10 는 시기적 의미가 변함.
NORMAL_PCT = 0.50
INVERTED_PCT = 0.15

# 5y 데이터 부족 시 절대 임계 fallback (이전 로직).
FALLBACK_NORMAL_BPS = 50.0
FALLBACK_INVERTED_BPS = -10.0


def _classify_regime_pct(percentile: float) -> Literal["normal", "flat", "inverted"]:
    if percentile > NORMAL_PCT:
        return "normal"
    if percentile < INVERTED_PCT:
        return "inverted"
    return "flat"


def _classify_regime_abs(spread_bps: float) -> Literal["normal", "flat", "inverted"]:
    if spread_bps > FALLBACK_NORMAL_BPS:
        return "normal"
    if spread_bps < FALLBACK_INVERTED_BPS:
        return "inverted"
    return "flat"


@register_skill(name="compute_kr_yield_curve", category="risk")
def compute_kr_yield_curve(
    treasury_3y: pd.Series, treasury_10y: pd.Series, as_of: date,
) -> KRYieldCurveSnapshot:
    """한국 국고채 yield curve 진단. 미국과 별도 사이클 가능 (BOK vs Fed 정책차)."""
    if treasury_3y is None or treasury_3y.empty or treasury_10y.empty:
        return KRYieldCurveSnapshot(
            treasury_3y=0.0, treasury_10y=0.0, spread_10y_3y_bps=0.0,
            inverted=False, percentile_5y=0.5, regime="flat",
            source_date=as_of, staleness_days=99,
        )

    y3 = float(treasury_3y.iloc[-1])
    y10 = float(treasury_10y.iloc[-1])
    spread_bps = (y10 - y3) * 100

    # 5y percentile (일별 정렬 기준). 데이터 부족 시 절대 임계 fallback.
    aligned = pd.concat([treasury_3y, treasury_10y], axis=1, join="inner").dropna()
    if len(aligned) >= 252:
        aligned.columns = ["y3", "y10"]
        spread_series = (aligned["y10"] - aligned["y3"]) * 100
        last_5y = spread_series.tail(252 * 5)
        percentile = float((last_5y < spread_bps).sum() / max(len(last_5y), 1))
        regime = _classify_regime_pct(percentile)
    else:
        percentile = 0.5
        regime = _classify_regime_abs(spread_bps)

    return KRYieldCurveSnapshot(
        treasury_3y=y3,
        treasury_10y=y10,
        spread_10y_3y_bps=spread_bps,
        inverted=spread_bps < 0,
        percentile_5y=percentile,
        regime=regime,
        source_date=as_of,
    )
