"""pykrx KR market fetcher — KOSPI200 valuation + foreign flow.

Critical: Windows pykrx KOSPI200 API mismatch (Issue #21). Linux only safe.
macOS arm64 smoke test 2026-05-24: PASS (Issue #21 manifest 안 됨, KRX 로그인 정상).
"""
from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _pykrx_fundamental_call(target_date: date) -> dict | None:
    """Returns KOSPI200 PBR/PER/DivYield at target_date (last KR business day if holiday)."""
    from pykrx import stock
    date_str = target_date.strftime("%Y%m%d")
    try:
        df = stock.get_index_fundamental(date_str, date_str, "1028")  # 1028 = KOSPI200
        if df.empty:
            return None
        row = df.iloc[0]
        return {
            "PBR": float(row.get("PBR", 0.0)),
            "PER": float(row.get("PER", 0.0)),
            "DIV_YIELD": float(row.get("배당수익률", 0.0)),
        }
    except Exception as e:
        logger.warning("pykrx KOSPI200 fundamental %s failed: %s", date_str, e)
        return None


def fetch_kospi200_valuation_monthly(
    start: date, end: date, cache_dir: Path | str,
) -> pd.DataFrame:
    """Monthly KOSPI200 valuation (PBR / PER / DIV_YIELD).

    Returns DataFrame indexed by month-end (or last business day) with columns
    PBR, PER, DIV_YIELD. Missing month → row 누락 (caller forward-fill 가능).
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "kospi200_valuation.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if (not df.empty and df.index.min().date() <= start
                and df.index.max().date() >= end):
            logger.debug("pykrx KOSPI200 valuation: cache hit (%s rows)", len(df))
            return df.loc[start:end]
        logger.info("pykrx KOSPI200 valuation: cache stale, refetching")

    month_ends = pd.date_range(start, end, freq="ME").to_pydatetime()
    records = []
    for me in month_ends:
        # KR business day adjustment — use month-end day; pykrx 가 holiday 면 None
        rec = _pykrx_fundamental_call(me.date())
        if rec is not None:
            records.append({"date": me.date(), **rec})
        time.sleep(0.3)  # pykrx rate limit safety
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.set_index("date")
        df.index = pd.to_datetime(df.index)
    df.to_parquet(cache_path)
    logger.info("pykrx KOSPI200 valuation: fetched %s months", len(df))
    return df


def _pykrx_foreign_call(start: date, end: date) -> pd.Series:
    """Returns pykrx KOSPI foreign net buy daily Series (KRW)."""
    from tradingagents.dataflows.pykrx_data import fetch_foreign_flow
    return fetch_foreign_flow(start, end, market="KOSPI")


def fetch_foreign_flow_monthly(
    start: date, end: date, cache_dir: Path | str,
) -> pd.DataFrame:
    """Monthly aggregated foreign flow (KOSPI 외국인 순매수).

    Returns DataFrame indexed by month-end with single column net_buy_krw
    (monthly aggregate KRW).
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "foreign_flow.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if (not df.empty and df.index.min().date() <= start
                and df.index.max().date() >= end):
            logger.debug("pykrx foreign flow: cache hit")
            return df.loc[start:end]
        logger.info("pykrx foreign flow: cache stale, refetching")

    daily = _pykrx_foreign_call(start, end)
    if daily is None or (hasattr(daily, "empty") and daily.empty):
        logger.warning("pykrx foreign flow returned empty for %s-%s", start, end)
        out = pd.DataFrame(columns=["net_buy_krw"])
        out.to_parquet(cache_path)
        return out
    # Aggregate to monthly — sum of daily net buy.
    # daily is pd.Series indexed by date; resample monthly.
    monthly = daily.resample("ME").sum()
    out = monthly.to_frame("net_buy_krw")
    out.to_parquet(cache_path)
    logger.info("pykrx foreign flow: fetched %s months", len(out))
    return out
