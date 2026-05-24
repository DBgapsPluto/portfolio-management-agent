"""FRED latest-vintage fetcher — thin wrapper + parquet cache.

기존 dataflows.fred.fetch_fred_series 를 wrap. Daily series 는 revise 없으므로
latest-vintage = 모든 시점 같음. Revised series (CFNAI, NFCI, GDPNOW 등) 는
fetcher_alfred 사용.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series

logger = logging.getLogger(__name__)


# C1 fetch 대상 FRED series — spec section 3.2 참조. ALFRED 대상 (revising) 은 제외.
FRED_QUARTERLY_SERIES: list[str] = [
    # Yield curve
    "DGS2", "DGS5", "DGS10", "DGS30",
    # Inflation (CPIAUCSL 은 ALFRED 으로 vintage fetch — 여기 latest-only 도 cross-check)
    "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE",
    # Inflation expectations
    "T5YIFR", "MICH",
    # Real yields (no revise, daily)
    "DFII10", "DFII5",
    # Credit
    "BAA", "AAA", "BAA10Y",
    # FX
    "DEXKOUS", "DTWEXM",
    # Cash
    "TB3MS",
    # Vol
    "VIXCLS",
    # Recession dummy
    "USREC",
    # Labor (UNRATE 은 ALFRED — 여기 latest cross-check)
    "UNRATE",
]


def fetch_fred_latest(
    series_id: str,
    start: date,
    end: date,
    cache_dir: Path | str,
) -> pd.Series:
    """Latest-vintage FRED fetch with parquet cache.

    Cache strategy: per-series single parquet. Cache hit → read; miss → fetch + write.

    Args:
        series_id: FRED native ID (e.g., "DGS10"). NOT the alias map key
                   (use raw FRED ID, since cache file 이 series_id 로 명명).
        start, end: date range (inclusive).
        cache_dir: e.g., `backtest/historical/raw/fred/`.

    Returns:
        pd.Series indexed by date.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{series_id}.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        series = df["value"]
        series.name = series_id
        # Verify cache covers [start, end]
        if series.index.min().date() <= start and series.index.max().date() >= end:
            logger.debug("FRED %s: cache hit (%s rows)", series_id, len(series))
            return series.loc[start:end]
        # Cache 가 부족 — fall through to refetch
        logger.info("FRED %s: cache stale, refetching", series_id)

    series = fetch_fred_series(series_id, start, end)
    series.name = series_id
    series.to_frame("value").to_parquet(cache_path)
    logger.info("FRED %s: fetched %s rows, cached", series_id, len(series))
    return series
