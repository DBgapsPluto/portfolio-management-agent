"""ECOS skill wrapper — with TieredCache."""
from datetime import date

import pandas as pd

from tradingagents.dataflows.ecos import fetch_ecos_series
from tradingagents.dataflows.series_cache import fetch_series_with_cache
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_ecos_series", category="macro")
def fetch_ecos_series_skill(
    name: str, start: date, end: date, api_key: str | None = None, freq: str = "M",
    as_of_date: date | None = None,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.Series:
    """Cache-first ECOS fetcher.

    Cache key: ({name}_{freq}, as_of_date or end). ECOS는 freq별 endpoint가
    다르므로 namespace에 freq 포함.
    """
    def _live() -> pd.Series:
        return fetch_ecos_series(
            name, start, end, api_key=api_key, freq=freq, as_of_date=as_of_date,
        )

    if not use_cache:
        return _live()

    cache_key = f"{name}_{freq}"
    return fetch_series_with_cache(
        _live,
        namespace="ecos",
        cache_key=cache_key,
        as_of=as_of_date or end,
        max_staleness=max_staleness,
    )
