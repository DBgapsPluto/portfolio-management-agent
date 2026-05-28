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

    필수 필드 누락 또는 파싱 실패 시 None 반환.
    """
    raise NotImplementedError


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
    raise NotImplementedError


def compute_tracking_error_12m(
    metrics: pd.DataFrame,
    ticker: str,
    index_returns: pd.Series | None = None,
) -> float | None:
    """12개월 추적오차 (annualized, % 단위).

    우선순위:
      1. KRX 공시 tracking_rate (% 단위) std (60일 이상 필요)
      2. fallback: market_price daily returns vs index_returns std of difference ×√252×100
      3. 데이터 부족 시 None
    """
    raise NotImplementedError


def compute_premium_discount_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days median |premium_discount|. 부족 시 None."""
    raise NotImplementedError


def compute_volume_per_aum_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days median (trade_value_krw / aum_krw). 유동성 proxy. 부족 시 None."""
    raise NotImplementedError
