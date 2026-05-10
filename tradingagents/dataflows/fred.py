import logging
import os
from datetime import date, timedelta

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


FRED_SERIES = {
    "us_10y": "DGS10",
    "us_2y": "DGS2",
    "us_3m": "DGS3MO",
    "us_cpi": "CPIAUCSL",
    "us_core_cpi": "CPILFESL",
    "us_unrate": "UNRATE",
    "us_payems": "PAYEMS",
    "fed_balance_sheet": "WALCL",
    "us_policy_rate": "DFF",
    "us_ig_oas": "BAMLC0A0CM",
    "us_hy_oas": "BAMLH0A0HYM2",
    "vix_close": "VIXCLS",
}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_fred_call(series_id: str, start: date, end: date, api_key: str) -> pd.Series:
    """Wrapped for mocking + transient retry."""
    from fredapi import Fred
    fred = Fred(api_key=api_key)
    return fred.get_series(series_id, observation_start=start, observation_end=end)


def _publication_cutoff(as_of_date: date, friendly_key: str) -> date:
    """Latest data point that was actually published by as_of_date.

    Look-ahead bias prevention: e.g., May CPI is released ~mid-June, so a
    simulation with as_of=2026-05-25 must NOT see May CPI.
    """
    lag = DEFAULT_CONFIG["publication_lag_days"].get(friendly_key, 1)
    return as_of_date - timedelta(days=lag)


def fetch_fred_series(
    series_id: str, start: date, end: date, api_key: str | None = None,
    as_of_date: date | None = None,
) -> pd.Series:
    """Fetch a single FRED series with point-in-time integrity.

    Args:
        as_of_date: If provided, truncates to data published by that date
            (publication lag applied per DEFAULT_CONFIG['publication_lag_days']).
            None means use raw end (live mode).
    """
    key = api_key or os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY not set")

    resolved = FRED_SERIES.get(series_id, series_id)
    series = _raw_fred_call(resolved, start, end, key)

    if as_of_date is not None:
        cutoff = _publication_cutoff(as_of_date, series_id)
        series = series[series.index.date <= cutoff]
        logger.debug(
            "FRED %s point-in-time cutoff %s (as_of=%s, lag applied)",
            series_id, cutoff, as_of_date,
        )

    return series
