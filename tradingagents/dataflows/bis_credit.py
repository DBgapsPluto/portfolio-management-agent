"""BIS Total Credit to Non-Financial Sector fetcher (China-focused).

Reference: BIS Total Credit Statistics (BIS_TC2), Biggs-Mayer-Pick 2010 JMCB.
Source: bis.org/statistics/totcredit/totcredit.xlsx (Quarterly Series sheet).

Vintage-aware: column position of code 'Q:CN:P:A:M:770:A' varies between BIS xlsx
vintages → dynamic discovery via _find_bis_code_position.
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

BIS_TOTCREDIT_URL: Final[str] = (
    "https://www.bis.org/statistics/totcredit/totcredit.xlsx"
)
# Target: Quarterly, China, Private non-financial sector, All sectors lending,
# Market value, Percent of GDP (770), Adjusted for breaks (A).
BIS_CN_CREDIT_CODE: Final[str] = "Q:CN:P:A:M:770:A"


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_bis_fetch() -> bytes:
    req = urllib.request.Request(BIS_TOTCREDIT_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _find_bis_code_position(
    header_df: pd.DataFrame, code: str, max_rows: int = 15,
) -> tuple[int | None, int | None]:
    """Search first max_rows for the BIS series code, return (row_idx, col_idx)."""
    for i in range(min(max_rows, len(header_df))):
        row_str = header_df.iloc[i].astype(str)
        matches = row_str[row_str == code]
        if len(matches) > 0:
            return i, matches.index[0]
    return None, None


def fetch_bis_china_credit(as_of: date | None = None) -> pd.Series:
    """BIS Quarterly: China Private Non-Financial Credit / GDP (%).

    Used by F12 china_credit_impulse (Biggs-Mayer-Pick 2010).
    Returns pd.Series indexed by quarter_end, dtype float, name='cn_credit_gdp_pct'.

    Vintage-aware: dynamically finds column for code 'Q:CN:P:A:M:770:A'.
    Raises ValueError if code not found.
    """
    data = _raw_bis_fetch()
    header_df = pd.read_excel(
        io.BytesIO(data), sheet_name="Quarterly Series",
        header=None, nrows=15,
    )
    code_row, code_col = _find_bis_code_position(header_df, BIS_CN_CREDIT_CODE)
    if code_row is None:
        raise ValueError(
            f"BIS code {BIS_CN_CREDIT_CODE} not found in xlsx — "
            f"vintage schema may have changed."
        )
    df = pd.read_excel(
        io.BytesIO(data), sheet_name="Quarterly Series",
        skiprows=code_row + 1, usecols=[0, code_col],
        header=None, names=["date", "cn_credit_gdp_pct"],
    )
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna().set_index("date")
    s = df["cn_credit_gdp_pct"].astype(float)
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s


__all__ = [
    "fetch_bis_china_credit",
    "_find_bis_code_position",
    "BIS_TOTCREDIT_URL",
    "BIS_CN_CREDIT_CODE",
]
