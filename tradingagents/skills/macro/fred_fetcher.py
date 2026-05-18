"""Skill-layer wrapper for FRED series fetch — with TieredCache."""
from datetime import date

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.dataflows.series_cache import fetch_series_with_cache
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_fred_series", category="macro")
def fetch_fred_series_skill(
    series: str, start: date, end: date, api_key: str | None = None,
    as_of_date: date | None = None,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.Series:
    """Cache-first FRED fetcher.

    Cache key: (series, as_of_date or end). 같은 날 재실행은 0 API.
    Live failure → max_staleness일 walk-back으로 stale fallback.
    use_cache=False면 항상 live (테스트용).
    """
    def _live() -> pd.Series:
        return fetch_fred_series(
            series, start, end, api_key=api_key, as_of_date=as_of_date,
        )

    if not use_cache:
        return _live()

    return fetch_series_with_cache(
        _live,
        namespace="fred",
        cache_key=series,
        as_of=as_of_date or end,
        max_staleness=max_staleness,
    )
