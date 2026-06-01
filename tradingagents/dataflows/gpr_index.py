"""Caldara-Iacoviello Geopolitical Risk Index fetcher.

Reference: Caldara-Iacoviello 2022 AER "Measuring Geopolitical Risk".
Source: matteoiacoviello.com/gpr_files/ (Excel, monthly 1900+ / daily 1985+).
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

GPR_MONTHLY_URL: Final[str] = (
    "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
)
GPR_DAILY_URL: Final[str] = (
    "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_gpr_fetch(url: str) -> bytes:
    """Fetch raw bytes from Iacoviello URL with retry."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_gpr_index(
    frequency: str = "monthly",
    series: str = "GPR",
    as_of: date | None = None,
) -> pd.Series:
    """Caldara-Iacoviello GPR Index, monthly or daily.

    frequency: 'monthly' (GPR 1900+) | 'daily' (GPRD 1985+)
    series: 'GPR' (global), 'GPRC_KOR'/'GPRC_CHN'/etc. (country-specific).
            Falls back to default ('GPR' for monthly, 'GPRD' for daily) if not in columns.
    """
    if frequency == "monthly":
        url, date_col, default_series = GPR_MONTHLY_URL, "month", "GPR"
    else:
        url, date_col, default_series = GPR_DAILY_URL, "date", "GPRD"

    data = _raw_gpr_fetch(url)
    df = pd.read_excel(io.BytesIO(data), sheet_name="Sheet1")
    df["_date"] = pd.to_datetime(df[date_col])
    df = df.set_index("_date")

    target_series = series if series in df.columns else default_series
    if target_series not in df.columns:
        raise ValueError(
            f"GPR series {target_series!r} not in columns. "
            f"Available: {list(df.columns)[:10]}..."
        )

    s = df[target_series].astype(float).rename(target_series.lower())
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s.dropna()


__all__ = ["fetch_gpr_index", "GPR_MONTHLY_URL", "GPR_DAILY_URL"]
