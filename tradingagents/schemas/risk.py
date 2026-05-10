from typing import Literal

from pydantic import Field

from tradingagents.schemas._base import StalenessAware


class VolatilitySnapshot(StalenessAware):
    index_name: Literal["VIX", "VKOSPI"]
    current_value: float = Field(ge=0)
    zscore_30d: float
    percentile_5y: float = Field(ge=0, le=1)


class SpreadSnapshot(StalenessAware):
    region: Literal["US_IG", "US_HY", "KR_IG"]
    current_bps: float
    percentile_5y: float = Field(ge=0, le=1)
    widening: bool


class SentimentSnapshot(StalenessAware):
    index_name: Literal["fear_greed_cnn", "fear_greed_alt"]
    current_value: int = Field(ge=0, le=100)
    label: Literal["extreme_fear", "fear", "neutral", "greed", "extreme_greed"]
    trend_7d: Literal["rising", "falling", "flat"]


class BreadthSnapshot(StalenessAware):
    market: Literal["KOSPI200", "SP500"]
    advancing_pct: float = Field(ge=0, le=1)
    declining_pct: float = Field(ge=0, le=1)
    new_highs_minus_lows: int


class PCASnapshot(StalenessAware):
    first_eigenvalue_share: float = Field(ge=0, le=1, description="Variance explained by PC1")
    n_assets_analyzed: int = Field(ge=2)
    is_concentrated: bool = Field(description="True if first_eigenvalue_share > 0.6")


class SystemicRiskScore(StalenessAware):
    """Subagent output."""
    score: float = Field(ge=0, le=10)
    regime: Literal["risk_on", "risk_off", "neutral"]
    drivers: list[str] = Field(min_length=1, max_length=5)
    reasoning: str = Field(max_length=300, default="")
