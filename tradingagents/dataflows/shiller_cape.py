"""Shiller US CAPE (PE10) fetcher.

Source: Yale econ.yale.edu/~shiller/data/ie_data.xls (1871+).
Reference: Asness 2003 FAJ, Campbell-Shiller 1988 RFS.
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

# econ.yale.edu/~shiller 는 2023-09 에서 멈춤 — Shiller 가 데이터를 shillerdata.com
# 으로 이전(2026.06+ 최신). ver= 캐시버스터 없이도 최신 파일을 반환한다.
SHILLER_URL: Final[str] = (
    "https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/"
    "downloads/c9b8cf0f-f01a-49f5-9ea5-d19443390ab2/ie_data.xls"
)


def _decimal_year_to_date(dy: float) -> pd.Timestamp:
    """Shiller decimal year (1871.01 = Jan 1871) → first-of-month Timestamp."""
    if pd.isna(dy):
        return pd.NaT
    year = int(dy)
    month = round((dy - year) * 100)
    month = max(1, min(12, month))
    return pd.Timestamp(year=year, month=month, day=1)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_shiller_fetch() -> bytes:
    """Download raw xls bytes from Yale. Separately mockable + retriable."""
    req = urllib.request.Request(SHILLER_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_shiller_cape(as_of: date | None = None) -> pd.Series:
    """Monthly Shiller CAPE (cyclically adjusted P/E10).

    Returns pd.Series indexed by month-start Timestamp, dtype float, name='cape'.
    Drops NaN (early years before 10y rolling enough).
    """
    data = _raw_shiller_fetch()
    df = pd.read_excel(io.BytesIO(data), sheet_name="Data", skiprows=7)
    cape_col = "CAPE" if "CAPE" in df.columns else "TR CAPE"
    df["_date"] = df["Date"].apply(_decimal_year_to_date)
    df = df.dropna(subset=[cape_col, "_date"]).set_index("_date")
    s = df[cape_col].astype(float).rename("cape")
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s


__all__ = ["fetch_shiller_cape", "_decimal_year_to_date", "SHILLER_URL"]
