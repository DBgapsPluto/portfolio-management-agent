"""Tier-2 — Economic release surprise (예상 vs 실제) + ESI 누적 인덱스.

macro_quant는 FRED actual 시리즈만 받음. forecast vs actual의 차이 (surprise)는
어디에도 없으므로 NEW 정보. 발표 데이터 자체는 Tier-5 SAVE ingestor가 채우거나
향후 외부 API에서 fetch.

본 skill은 계산 로직 only (input → 정규화 → 집계).
"""
from datetime import date, timedelta
from typing import Literal

import numpy as np

from tradingagents.schemas.news import (
    ReleaseBias, ReleaseSurprise, ReleaseSurpriseSnapshot, SurpriseDirection,
)
from tradingagents.skills.registry import register_skill


# 인플레/고용/성장이 강하게 나오면 hawkish (긴축 명분 ↑) 라벨링.
# 매크로 indicator 키워드 → bias 부호.
_HAWKISH_KEYWORDS = (
    "cpi", "ppi", "core", "wage", "employment", "payroll", "nonfarm",
    "ism", "pmi", "gdp", "retail", "industrial",
    "물가", "고용", "취업", "산업생산",
)
_DOVISH_INVERTED = (
    "unemployment rate", "jobless claims", "초기 실업",
    # 이런 지표는 actual 값이 클수록 dovish
)


def _is_dovish_inverted(indicator: str) -> bool:
    lower = indicator.lower()
    return any(k in lower for k in _DOVISH_INVERTED)


def _bias_score_one(r: ReleaseSurprise) -> float:
    """단일 surprise의 macro bias 기여도. zscore가 있으면 그걸 사용.

    + = hawkish (긴축 명분, dollar 강세, bond 약세)
    - = dovish
    """
    if r.surprise_zscore is None or r.surprise is None:
        return 0.0
    z = r.surprise_zscore
    indicator_lower = r.indicator.lower()
    if _is_dovish_inverted(indicator_lower):
        # 실업률 surprise +면 dovish
        return -z
    if any(k in indicator_lower for k in _HAWKISH_KEYWORDS):
        return z
    return 0.0


def _classify_direction(
    surprise: float | None, importance: int,
) -> SurpriseDirection:
    if surprise is None:
        return "unknown"
    # 단순 임계: 거의 일치하면 inline
    if abs(surprise) < 0.05:
        return "inline"
    return "positive" if surprise > 0 else "negative"


def normalize_release(
    raw: ReleaseSurprise, historical_std: float | None = None,
) -> ReleaseSurprise:
    """forecast/actual을 받아 surprise + zscore + direction 채워서 반환.

    historical_std가 있으면 zscore 계산. 없으면 그대로 None.
    """
    if raw.actual is None or raw.forecast is None:
        return raw.model_copy(update={
            "surprise": None,
            "surprise_zscore": None,
            "direction": "unknown",
        })
    surprise = float(raw.actual - raw.forecast)
    zscore = (
        float(surprise / historical_std) if historical_std and historical_std > 0
        else None
    )
    direction = _classify_direction(surprise, raw.importance)
    return raw.model_copy(update={
        "surprise": surprise,
        "surprise_zscore": zscore,
        "direction": direction,
    })


@register_skill(name="compute_release_surprise_snapshot", category="news")
def compute_release_surprise_snapshot(
    releases_30d: list[ReleaseSurprise], as_of: date,
) -> ReleaseSurpriseSnapshot:
    """Aggregate release list into snapshot.

    releases_30d: 최근 30일 발표 (normalize_release로 이미 정규화된 것).
    """
    today = [r for r in releases_30d if r.release_date == as_of]
    five_days_ago = as_of - timedelta(days=5)
    last_5d = [r for r in releases_30d if r.release_date >= five_days_ago]

    # ESI: 최근 30d zscore 평균 (EWMA로 가중)
    zscores = [r.surprise_zscore for r in releases_30d if r.surprise_zscore is not None]
    surprise_idx_30d = float(np.mean(zscores)) if zscores else 0.0

    high_importance_today = sum(1 for r in today if r.importance >= 3)

    bias_score = sum(_bias_score_one(r) for r in releases_30d)
    bias: ReleaseBias
    if bias_score > 1.0:
        bias = "hawkish_surprise"
    elif bias_score < -1.0:
        bias = "dovish_surprise"
    else:
        bias = "balanced"

    return ReleaseSurpriseSnapshot(
        today_releases=today,
        last_5d_releases=last_5d,
        surprise_index_30d=surprise_idx_30d,
        high_importance_today=high_importance_today,
        bias_30d=bias,
        source_date=as_of,
    )
