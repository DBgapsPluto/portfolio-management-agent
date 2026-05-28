"""Gilchrist-Zakrajsek Excess Bond Premium fetcher.

Reference: Gilchrist-Zakrajsek 2012 AER "Credit Spreads and Business Cycle".
Source: federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv (monthly 1973+).
"""
from __future__ import annotations

import io
import logging
import urllib.request
from datetime import date
from typing import Final

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)

FED_EBP_URL: Final[str] = (
    "https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv"
)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_gz_ebp_fetch() -> bytes:
    req = urllib.request.Request(FED_EBP_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_gz_ebp(as_of: date | None = None) -> pd.Series:
    """Monthly Excess Bond Premium (Federal Reserve Board).

    Returns pd.Series indexed by month-start, dtype float, name='ebp'.
    """
    data = _raw_gz_ebp_fetch()
    df = pd.read_csv(io.BytesIO(data), parse_dates=["date"])
    df = df.set_index("date")
    s = df["ebp"].astype(float).rename("ebp")
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s.dropna()


__all__ = ["fetch_gz_ebp", "FED_EBP_URL"]
