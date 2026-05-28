"""ETF 일별 메트릭 fetch + 계산 (Phase 2a, 2026-05-29).

KRX OpenAPI 의 ETF 일별 detail 을 fetch 해서 ParquetCache 에 저장하고,
window slice + 메트릭 계산 (TE 12m, |괴리율| 30d median, volume/AUM 30d median)
함수 제공. compute_impl_score 의 4-요소 입력으로 사용.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel

from tradingagents.dataflows.krx_openapi import (
    KRXOpenAPIError, fetch_etf_daily_detail,
)

logger = logging.getLogger(__name__)


# Default window for TE computation (12m + buffer).
DEFAULT_METRICS_WINDOW_DAYS: int = 400


class ETFDailyMetrics(BaseModel):
    """단일 ticker × 단일 날짜 의 ETF 메타데이터."""
    ticker: str
    trade_date: date
    nav: float
    market_price: float
    premium_discount: float
    volume: int
    trade_value_krw: float
    aum_krw: float
    tracking_rate: float | None = None


def _parse_krx_record(record: dict, basDd: date) -> ETFDailyMetrics | None:
    """KRX OpenAPI 단일 record (dict) → ETFDailyMetrics.

    필수 필드 누락 또는 파싱 실패 시 None 반환 + WARNING log.
    """
    try:
        ticker = str(record["ISU_SRT_CD"]).strip()
        nav = float(record["NAV"])
        market_price = float(record["TDD_CLSPRC"])
        volume = int(float(record["ACC_TRDVOL"]))
        trade_value = float(record["ACC_TRDVAL"])
        aum = float(record["MKTCAP"])
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(
            "_parse_krx_record: skipping malformed record (%s): %r",
            e, record,
        )
        return None

    # premium_discount = market_price / nav - 1 (NAV=0 보호)
    if nav <= 0:
        return None
    premium_discount = market_price / nav - 1.0

    # tracking_rate 는 optional
    tracking_rate: float | None = None
    if "TRC_RT" in record:
        try:
            tracking_rate = float(record["TRC_RT"])
        except (ValueError, TypeError):
            tracking_rate = None

    return ETFDailyMetrics(
        ticker=ticker,
        trade_date=basDd,
        nav=nav,
        market_price=market_price,
        premium_discount=premium_discount,
        volume=volume,
        trade_value_krw=trade_value,
        aum_krw=aum,
        tracking_rate=tracking_rate,
    )


def _business_days(start: date, end: date) -> list[date]:
    """월~금 (공휴일 무관, KRX 응답이 빈 list 면 skip)."""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon=0 ~ Fri=4
            days.append(current)
        current += timedelta(days=1)
    return days


def _cache_file(cache_path: Path, basDd: date) -> Path:
    """cache_path/etf_metrics/YYYY-MM-DD.parquet"""
    cache_dir = cache_path / "etf_metrics"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{basDd.isoformat()}.parquet"


def fetch_etf_metrics_window(
    tickers: list[str],
    start: date,
    end: date,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    """ticker × date multi-index DataFrame.

    Columns: nav, market_price, premium_discount, volume, trade_value_krw,
             aum_krw, tracking_rate.
    누락 날짜는 KRX OpenAPI fetch, ParquetCache 영구 저장.
    """
    days = _business_days(start, end)
    all_rows: list[dict] = []
    cache_root: Path | None = None
    if cache_path is not None:
        cache_root = Path(cache_path)

    for d in days:
        cache_file_path: Path | None = (
            _cache_file(cache_root, d) if cache_root is not None else None
        )
        # 1. 캐시 hit 시 load
        day_rows: list[dict] | None = None
        if cache_file_path is not None and cache_file_path.exists():
            try:
                day_df = pd.read_parquet(cache_file_path)
                day_rows = day_df.to_dict(orient="records")
            except Exception as e:
                logger.warning("cache read failed for %s: %s — refetching", d, e)
                day_rows = None

        # 2. 캐시 miss → fetch
        if day_rows is None:
            try:
                records = fetch_etf_daily_detail(d, ticker=None)
            except KRXOpenAPIError:
                # 호출자가 처리할 수 있도록 raise
                raise
            day_rows = []
            for rec in records:
                parsed = _parse_krx_record(rec, d)
                if parsed is not None:
                    day_rows.append(parsed.model_dump())
            # 캐시 저장 (빈 list 도 저장 — 공휴일 표시)
            if cache_file_path is not None:
                pd.DataFrame(day_rows).to_parquet(cache_file_path)

        # 3. ticker 필터링
        for row in day_rows:
            if row["ticker"] in tickers:
                all_rows.append(row)

    if not all_rows:
        return pd.DataFrame(
            columns=["nav", "market_price", "premium_discount", "volume",
                     "trade_value_krw", "aum_krw", "tracking_rate"],
            index=pd.MultiIndex.from_arrays([[], []], names=["ticker", "trade_date"]),
        )

    df = pd.DataFrame(all_rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df = df.set_index(["ticker", "trade_date"]).sort_index()
    return df


def compute_tracking_error_12m(
    metrics: pd.DataFrame,
    ticker: str,
    index_returns: pd.Series | None = None,
) -> float | None:
    """12개월 추적오차 (annualized, % 단위).

    우선순위:
      1. KRX 공시 tracking_rate (% 단위) std (60일 이상 필요)
      2. fallback: market_price daily returns vs index_returns 의 std×√252×100
      3. 부족 시 None
    """
    if ticker not in metrics.index.get_level_values("ticker"):
        return None
    sub = metrics.xs(ticker, level="ticker")
    if sub.empty:
        return None

    # 1순위: tracking_rate 의 std (pp)
    if "tracking_rate" in sub.columns:
        rates = sub["tracking_rate"].dropna()
        if len(rates) >= 60:
            recent = rates.tail(252)
            return float(recent.std())

    # 2순위: market_price vs index_returns
    if index_returns is None:
        return None
    fund_returns = sub["market_price"].pct_change().dropna()
    if len(fund_returns) < 60:
        return None
    aligned_fund, aligned_idx = fund_returns.align(index_returns, join="inner")
    diff = (aligned_fund - aligned_idx).dropna()
    if len(diff) < 60:
        return None
    return float(diff.std() * np.sqrt(252) * 100.0)


def compute_premium_discount_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days median |premium_discount|. 부족 시 None."""
    if ticker not in metrics.index.get_level_values("ticker"):
        return None
    sub = metrics.xs(ticker, level="ticker")
    if "premium_discount" not in sub.columns:
        return None
    pd_series = sub["premium_discount"].dropna().tail(n_days)
    if len(pd_series) < min(n_days, 10):  # 최소 10일은 있어야
        return None
    return float(pd_series.abs().median())


def compute_volume_per_aum_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days median (trade_value_krw / aum_krw). 유동성 proxy. 부족 시 None."""
    if ticker not in metrics.index.get_level_values("ticker"):
        return None
    sub = metrics.xs(ticker, level="ticker")
    if "trade_value_krw" not in sub.columns or "aum_krw" not in sub.columns:
        return None
    valid = sub[(sub["aum_krw"] > 0) & sub["trade_value_krw"].notna()].tail(n_days)
    if len(valid) < min(n_days, 10):
        return None
    ratio = valid["trade_value_krw"] / valid["aum_krw"]
    return float(ratio.median())
