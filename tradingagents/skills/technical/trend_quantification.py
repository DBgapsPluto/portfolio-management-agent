"""Tier-2 — Trend quantification (연속값 + time-in-state + dual momentum + accel)."""
from typing import Literal

import numpy as np
import pandas as pd
import pandas_ta as ta

from tradingagents.schemas.technical import TrendQuantification
from tradingagents.skills.registry import register_skill


BenchmarkLabel = Literal["KOSPI200", "SPY", "none"]


def _ma_cross_days(close: pd.Series, ma: pd.Series) -> int:
    """Days since the most recent sign change of (close - ma).

    If no cross found within the available window, returns the window length
    (i.e., state has held throughout)."""
    diff = (close > ma).astype(int).diff().fillna(0)
    cross_idx = diff[diff != 0].index
    if len(cross_idx) == 0:
        return int(len(close) - 200)
    last = int(cross_idx[-1])
    return int(close.index[-1] - last)


def _trend_strength(
    distance_ma200_pct: float, ma50_above_ma200: bool, adx: float, rsi: float,
) -> float:
    """合成 -1..+1.

    ⚠️ HARDCODED CAVEAT (#2, 2026-05 audit):
      가중치 (0.40 / 0.30 / 0.20 / 0.10) 와 정규화 분모 (/10, /50, /50)
      모두 **학술/실무 근거 없는 임의 선택**. 합이 1.0이 되도록 맞춘 것.
      backtest 캘리브레이션 TODO. 현재는 LLM이 raw score를 직접 해석하지 않고
      sector_rotation/universe_breadth 같은 합성 신호에 흡수돼서 systematic bias
      위험이 낮지만, ranking 정확성에 영향 가능.
      Stage 3 candidate_selector 백테스트 결과로 weights 재추정 권장.
    """
    score = (
        0.40 * float(np.clip(distance_ma200_pct / 10.0, -1.0, 1.0))
        + 0.30 * float(np.clip(adx / 50.0, 0.0, 1.0)) * (1.0 if ma50_above_ma200 else -1.0)
        + 0.20 * (1.0 if ma50_above_ma200 else -1.0)
        + 0.10 * float(np.clip((rsi - 50.0) / 50.0, -1.0, 1.0))
    )
    return float(np.clip(score, -1.0, 1.0))


@register_skill(name="quantify_trend", category="technical")
def quantify_trend(
    prices: pd.DataFrame, ticker: str,
    benchmark_close: pd.Series | None = None,
    benchmark_label: BenchmarkLabel = "none",
) -> TrendQuantification:
    """Compute Tier-2 trend quantification for one ticker.

    benchmark_close: Daily close of the benchmark, aligned by date. If None or
        too short, relative momentum = 0 and benchmark="none".
    """
    sub = prices[prices["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    if len(sub) < 252:
        raise ValueError(f"Need ≥252 data points for {ticker}, got {len(sub)}")

    close = sub["close"].astype(float).reset_index(drop=True)
    high = sub["high"].astype(float).reset_index(drop=True)
    low = sub["low"].astype(float).reset_index(drop=True)

    ma200_series = ta.sma(close, length=200)
    ma50_series = ta.sma(close, length=50)
    rsi = float(ta.rsi(close, length=14).iloc[-1])
    adx = float(ta.adx(high, low, close, length=14).iloc[-1, 0])

    last = float(close.iloc[-1])
    ma200 = float(ma200_series.iloc[-1])
    ma50 = float(ma50_series.iloc[-1])
    distance_ma200_pct = (last - ma200) / ma200 * 100.0 if ma200 > 0 else 0.0
    distance_ma50_pct = (last - ma50) / ma50 * 100.0 if ma50 > 0 else 0.0
    ma50_above_ma200 = ma50 > ma200

    time_in_state = _ma_cross_days(close, ma200_series)

    strength = _trend_strength(distance_ma200_pct, ma50_above_ma200, adx, rsi)

    # Momentum windows
    m3 = float(close.iloc[-1] / close.iloc[-64] - 1.0)
    m12 = float(close.iloc[-1] / close.iloc[-253] - 1.0)

    # Relative vs benchmark
    if (
        benchmark_close is not None
        and len(benchmark_close.dropna()) >= 253
    ):
        bc = benchmark_close.dropna().astype(float)
        b3 = float(bc.iloc[-1] / bc.iloc[-64] - 1.0)
        b12 = float(bc.iloc[-1] / bc.iloc[-253] - 1.0)
        m3_rel = m3 - b3
        m12_rel = m12 - b12
        bench: BenchmarkLabel = benchmark_label
    else:
        m3_rel = 0.0
        m12_rel = 0.0
        bench = "none"

    # Acceleration: annualized 3m vs 12m
    m3_ann = (1.0 + m3) ** 4 - 1.0
    accel = m3_ann - m12

    last_date = sub["date"].iloc[-1]
    source_date = (
        last_date.date() if hasattr(last_date, "date")
        else pd.Timestamp(last_date).date()
    )

    return TrendQuantification(
        ticker=ticker,
        trend_strength_score=strength,
        time_in_state_days=time_in_state,
        distance_ma200_pct=distance_ma200_pct,
        distance_ma50_pct=distance_ma50_pct,
        momentum_3m_abs=m3,
        momentum_3m_rel=m3_rel,
        momentum_12m_abs=m12,
        momentum_12m_rel=m12_rel,
        momentum_acceleration=accel,
        benchmark=bench,
        source_date=source_date,
    )
