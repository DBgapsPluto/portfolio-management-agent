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
