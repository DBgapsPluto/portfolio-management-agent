from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from tradingagents.schemas._base import StalenessAware


class TrendState(str, Enum):
    STRONG_UPTREND = "strong_uptrend"
    UPTREND = "uptrend"
    NEUTRAL = "neutral"
    DOWNTREND = "downtrend"
    BREAKDOWN = "breakdown"


class IndicatorPanel(StalenessAware):
    ticker: str = Field(pattern=r"^A\d{6}[A-Z0-9]?$")
    ma200: float
    ma50: float
    rsi: float = Field(ge=0, le=100)
    macd_signal: float
    atr: float = Field(ge=0)


class ETFRanking(BaseModel):
    """Pure derivation from price data — no staleness here, parent carries it."""
    ticker: str
    name: str
    momentum_3m: float
    momentum_6m: float
    momentum_12m: float
    rank_in_category: int = Field(ge=1)


class Cluster(BaseModel):
    cluster_id: str
    members: list[str] = Field(min_length=2, description="Tickers in this cluster")
    avg_internal_correlation: float = Field(ge=-1, le=1)
    category_label: str = Field(max_length=80, description="Human label for the theme")


# ---------- Tier-1: Indicator 깊이 ----------

DivergenceKind = Literal["none", "bullish", "bearish"]
WeeklyTrend = Literal["up", "down", "neutral"]


class ExtendedIndicatorPanel(StalenessAware):
    """Tier-1 확장 — Bollinger / ADX / Stochastic / Volume / Divergence / Weekly.

    단일 ETF에 대해 한 번 계산. 188 ETF면 188 instance.
    OHLCV만으로 다 계산 (외부 fetch 0).
    """
    ticker: str = Field(pattern=r"^A[A-Z0-9]{6}$")

    # Bollinger (length=20, std=2)
    bb_percent_b: float = Field(
        description="%B: (price - lower) / (upper - lower). <0 oversold, >1 overbought."
    )
    bb_bandwidth: float = Field(
        ge=0,
        description="(upper - lower) / middle. Squeeze < ~5% (varies by asset).",
    )

    # ADX (length=14) — 추세 강도
    adx: float = Field(ge=0, le=100, description="<20 무추세, 20-40 추세, >40 강한 추세")

    # Stochastic (k=14, d=3) — 단기 over-bought/sold
    stoch_k: float = Field(ge=0, le=100)
    stoch_d: float = Field(ge=0, le=100)

    # Volume confirmations
    obv: float = Field(description="累계 OBV. 절대값보다 추세가 핵심.")
    obv_slope_20d: float = Field(description="OBV 최근 20일 slope sign (+ = 누적, - = 분산)")
    mfi: float = Field(ge=0, le=100, description="Money Flow Index. <20 oversold, >80 overbought.")

    # Divergence — 가격 vs indicator (최근 60일 윈도우)
    rsi_divergence: DivergenceKind
    macd_divergence: DivergenceKind

    # Multi-timeframe (주봉)
    weekly_ma50: float = Field(ge=0)
    weekly_rsi: float = Field(ge=0, le=100)
    weekly_trend: WeeklyTrend


# ---------- Tier-2: Trend 정량화 ----------


class TrendQuantification(StalenessAware):
    """Tier-2 — 추세를 범주형(enum)에서 연속값으로 끌어올림.

    distance, time-in-state, dual momentum, acceleration.
    """
    ticker: str = Field(pattern=r"^A[A-Z0-9]{6}$")

    trend_strength_score: float = Field(
        ge=-1, le=1,
        description="ADX/MA-cross/거리/RSI 합성. -1=강한 하락, +1=강한 상승.",
    )
    time_in_state_days: int = Field(
        ge=0, description="가격이 마지막으로 MA200 cross한 후 경과 일수."
    )
    distance_ma200_pct: float = Field(description="(price - MA200) / MA200 × 100.")
    distance_ma50_pct: float = Field(description="(price - MA50) / MA50 × 100.")

    momentum_3m_abs: float = Field(description="자체 3m 수익률 (raw).")
    momentum_3m_rel: float = Field(description="벤치마크 대비 3m 초과 수익률.")
    momentum_12m_abs: float
    momentum_12m_rel: float
    momentum_acceleration: float = Field(
        description="annualized(3m) - 12m. 양수=가속, 음수=감속."
    )
    benchmark: Literal["KOSPI200", "SPY", "none"] = Field(
        description="dual_momentum 계산에 쓴 벤치마크."
    )


# ---------- Tier-3: Universe Breadth (188 ETF 집계) ----------


BreadthRegime = Literal["broad_risk_on", "narrow", "broad_risk_off"]


class UniverseBreadthSnapshot(StalenessAware):
    """Tier-3 — universe 188 ETF의 시장 내부 상태 집계.

    한 번 계산해서 단일 snapshot. LLM에 그대로 노출 가능 (이미 압축).
    """
    n_total: int = Field(ge=0)
    n_eligible: int = Field(ge=0, description="MA200 계산 가능 (≥200d history)")
    pct_above_ma50: float = Field(ge=0, le=1)
    pct_above_ma200: float = Field(ge=0, le=1)
    new_52w_highs: int = Field(ge=0)
    new_52w_lows: int = Field(ge=0)
    advance_decline_5d_ratio: float = Field(
        ge=0, description="5일 advancing ETF / declining ETF (∞ 시 10으로 cap).",
    )
    ad_line_5d_slope: float = Field(
        description="AD line 5d 변화 부호 (+1/0/-1)",
    )
    universe_vol_median: float = Field(
        ge=0, description="188 ETF의 60d annualized vol median.",
    )
    universe_vol_z: float = Field(
        description="universe vol median의 1년치 z-score (regime 식별).",
    )
    regime: BreadthRegime


# ---------- Tier-4: Sector Rotation + Correlation regime ----------


CorrRegime = Literal["expansion", "stable", "compression"]


class CategoryMomentum(BaseModel):
    """카테고리 단위 집계 모멘텀 — universe.json의 category 필드 기준."""
    category: str
    n_etfs: int = Field(ge=0)
    mean_mom_3m: float
    mean_mom_12m: float
    rank: int = Field(ge=1, description="leadership rank — 1 = best")


class SectorRotationSnapshot(StalenessAware):
    """Tier-4 — 카테고리 leadership matrix + universe momentum dispersion +
    correlation regime change.
    """
    categories: list[CategoryMomentum] = Field(
        description="카테고리 list, mean_mom_3m DESC로 정렬.",
    )
    leader_category: str
    laggard_category: str
    momentum_spread_3m: float = Field(
        description="188 ETF의 mom_3m top decile mean - bot decile mean.",
    )
    correlation_median_60d: float = Field(ge=-1, le=1)
    correlation_median_252d: float = Field(ge=-1, le=1)
    correlation_change: float = Field(
        description="60d median - 252d median. + = 최근 correlation 증가 (위기형).",
    )
    correlation_regime: CorrRegime
