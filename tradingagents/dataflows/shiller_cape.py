"""Shiller US CAPE (PE10) fetcher.

Source: Yale econ.yale.edu/~shiller/data/ie_data.xls (1871+).
Reference: Asness 2003 FAJ, Campbell-Shiller 1988 RFS.
"""
from __future__ import annotations

import logging
import urllib.request
from datetime import date
from typing import Final

import pandas as pd

logger = logging.getLogger(__name__)

SHILLER_URL: Final[str] = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"


def _decimal_year_to_date(dy: float) -> pd.Timestamp:
    """Shiller decimal year (1871.01 = Jan 1871) → first-of-month Timestamp."""
    if pd.isna(dy):
        return pd.NaT
    year = int(dy)
    month = round((dy - year) * 100)
    month = max(1, min(12, month))
    return pd.Timestamp(year=year, month=month, day=1)


def fetch_shiller_cape(as_of: date | None = None) -> pd.Series:
    """Monthly Shiller CAPE (cyclically adjusted P/E10).

    Returns pd.Series indexed by month-start Timestamp, dtype float, name='cape'.
    Drops NaN (early years before 10y rolling enough).
    """
    req = urllib.request.Request(SHILLER_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        df = pd.read_excel(r, sheet_name="Data", skiprows=7)
    cape_col = "CAPE" if "CAPE" in df.columns else "TR CAPE"
    df["_date"] = df["Date"].apply(_decimal_year_to_date)
    df = df.dropna(subset=[cape_col, "_date"]).set_index("_date")
    s = df[cape_col].astype(float).rename("cape")
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s


__all__ = ["fetch_shiller_cape", "_decimal_year_to_date", "SHILLER_URL"]
