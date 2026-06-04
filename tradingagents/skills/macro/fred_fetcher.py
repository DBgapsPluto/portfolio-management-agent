"""Skill-layer wrapper for FRED series fetch — with TieredCache."""
import logging
from datetime import date

import pandas as pd

from tradingagents.dataflows.fred import FRED_SERIES, fetch_fred_series
from tradingagents.dataflows.pykrx_data import _run_with_timeout
from tradingagents.dataflows.series_cache import fetch_series_with_cache
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)

# fredapi 가 urlopen 을 timeout 없이 호출 → 무응답 series 에서 무한 hang.
_FRED_FETCH_TIMEOUT_S = 30


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
        try:
            return _run_with_timeout(
                lambda: fetch_fred_series(
                    series, start, end, api_key=api_key, as_of_date=as_of_date,
                ),
                _FRED_FETCH_TIMEOUT_S,
            )
        except TimeoutError:
            logger.warning(
                "FRED %s fetch %ds timeout — skip", series, _FRED_FETCH_TIMEOUT_S,
            )
            return pd.Series(dtype=float)

    if not use_cache:
        return _live()

    return fetch_series_with_cache(
        _live,
        namespace="fred",
        # logical name 대신 resolved series_id 로 캐시 — series 매핑 교체(예: china_cli
        # NOSTSAM→AASTSAM) 시 옛 series 캐시를 hit 하지 않도록 자동 분리.
        cache_key=FRED_SERIES.get(series, series),
        as_of=as_of_date or end,
        max_staleness=max_staleness,
    )
