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
