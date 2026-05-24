"""ALFRED (Archival FRED) vintage-aware fetch — Critical 1.

기존 FRED 의 latest-vintage 가 1991-Q1 CFNAI 의 *2024 년 revised 최종값* 을
반환 → backtest 의 look-ahead bias. ALFRED API 는 realtime_start 시점에 알려져
있던 값을 반환 → point-in-time 정합성.

7 revising series 대상:
- CFNAI: Chicago Fed National Activity Index (monthly)
- NFCI, ANFCI: National Financial Conditions Index (weekly)
- GDPNOW: Atlanta Fed GDPNow (2011+)
- UNRATE: Unemployment rate (Sahm rule input)
- CPIAUCSL: CPI All Items
- PCEPILFE: Core PCE

API: https://api.stlouisfed.org/fred/series/observations
     ?series_id=<id>&realtime_start=<quarter_end>&realtime_end=<quarter_end>
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date
from pathlib import Path

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


ALFRED_SERIES: list[str] = [
    "CFNAI", "NFCI", "ANFCI", "GDPNOW",
    "UNRATE", "CPIAUCSL", "PCEPILFE",
]


def _quarter_ends(start: date, end: date) -> list[date]:
    """[start, end] 사이의 분기 말 (Mar 31, Jun 30, Sep 30, Dec 31) 의 list."""
    quarter_ends = []
    target_months = [(3, 31), (6, 30), (9, 30), (12, 31)]
    for year in range(start.year, end.year + 1):
        for tm, td in target_months:
            qe = date(year, tm, td)
            if start <= qe <= end:
                quarter_ends.append(qe)
    return quarter_ends


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _call_alfred(series_id: str, realtime_date: date) -> float | None:
    """ALFRED API: 특정 realtime_date 시점의 series 의 최신 vintage value.

    Returns None if:
    - no observation available at realtime_date (pre-publish), OR
    - HTTP 400 ("Bad Request — series not yet published at realtime_start").
      이는 CFNAI/NFCI/ANFCI/GDPNOW/PCEPILFE 같은 series 가 일찍 발행되지
      않아서 1991-Q1 같은 옛 quarter end 에 vintage 가 부재한 경우 발생.
    """
    import requests
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY not set")
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "realtime_start": realtime_date.isoformat(),
        "realtime_end": realtime_date.isoformat(),
        "sort_order": "desc",
        "limit": 1,
    }
    resp = requests.get(url, params=params, timeout=15)
    # 400 = series not yet published at this realtime_start → graceful None.
    if resp.status_code == 400:
        return None
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    if not obs:
        return None
    val = obs[0].get("value")
    if val in (".", None, ""):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def fetch_alfred_vintage_quarterly(
    series_id: str,
    start: date,
    end: date,
    cache_dir: Path | str,
) -> pd.DataFrame:
    """각 quarter end 시점에 *알려져 있던* 값 (vintage-aware).

    Args:
        series_id: ALFRED series ID (e.g., "CFNAI").
        start, end: date range.
        cache_dir: e.g., `backtest/historical/raw/fred_alfred/`.

    Returns:
        DataFrame indexed by quarter end date, single column "vintage_value".
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{series_id}.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if not df.empty and df.index.min().date() <= start and df.index.max().date() >= end:
            logger.debug("ALFRED %s: cache hit (%s rows)", series_id, len(df))
            return df.loc[start:end]
        logger.info("ALFRED %s: cache stale, refetching", series_id)

    qs = _quarter_ends(start, end)
    logger.info("ALFRED %s: fetching %s quarter ends", series_id, len(qs))
    records = []
    for qe in qs:
        val = _call_alfred(series_id, qe)
        records.append({"date": qe, "vintage_value": val})
        time.sleep(0.6)  # FRED rate limit ~120/min → safe ~100/min
    df = pd.DataFrame(records).set_index("date")
    df.index = pd.to_datetime(df.index)
    df.to_parquet(cache_path)
    return df
