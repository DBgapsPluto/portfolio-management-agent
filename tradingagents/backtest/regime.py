"""NBER recession classifier + sample split utilities for PR2b validation.

USREC (FRED) = NBER 공식 recession dummy. Monthly. resample('QE').max() 으로
quarter 별 boolean (any month=1 in quarter → recession=True).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from tradingagents.skills.research.factor_calibration import HistoricalSample


def nber_recession_quarterly_from_series(
    usrec_monthly: pd.Series,
) -> pd.Series:
    """Monthly USREC → quarterly boolean (any month=1 → True).

    Args:
        usrec_monthly: pd.Series indexed by month, values ∈ {0, 1}.

    Returns:
        pd.Series indexed by quarter end (Mar 31 / Jun 30 / Sep 30 / Dec 31),
        bool dtype.
    """
    if usrec_monthly.empty:
        return pd.Series(dtype=bool)
    bool_monthly = (usrec_monthly > 0).astype(bool)
    quarterly = bool_monthly.resample("QE").max()
    return quarterly.astype(bool)


def nber_recession_quarterly_from_parquet(
    cache_path: Path | str,
) -> pd.Series:
    """Read USREC.parquet (from PR2a fetcher_fred cache) → quarterly bool.

    Args:
        cache_path: path to FRED USREC cache parquet.

    Returns:
        quarterly bool Series.
    """
    cache_path = Path(cache_path)
    if not cache_path.exists():
        return pd.Series(dtype=bool)
    df = pd.read_parquet(cache_path)
    series = df["value"]
    series.index = pd.to_datetime(series.index)
    return nber_recession_quarterly_from_series(series)


def split_samples_by_regime(
    samples: Sequence[HistoricalSample],
    recession_quarterly: pd.Series,
) -> tuple[list[HistoricalSample], list[HistoricalSample]]:
    """Partition samples into (expansion, recession) by date.

    Args:
        samples: list of HistoricalSample (with .date = YYYY-MM-DD string).
        recession_quarterly: bool Series indexed by quarter end date.

    Returns:
        (expansion_samples, recession_samples).
        Sample with date not in recession Series → expansion (default).
    """
    expansion, recession = [], []
    for s in samples:
        ts = pd.Timestamp(s.date)
        is_recession = bool(recession_quarterly.get(ts, False))
        if is_recession:
            recession.append(s)
        else:
            expansion.append(s)
    return expansion, recession
