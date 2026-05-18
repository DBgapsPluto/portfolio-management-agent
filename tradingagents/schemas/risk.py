from typing import Literal

from pydantic import Field

from tradingagents.schemas._base import StalenessAware


class VolatilitySnapshot(StalenessAware):
    index_name: Literal["VIX", "VKOSPI"]
    current_value: float = Field(ge=0)
    zscore_30d: float
    percentile_5y: float = Field(ge=0, le=1)
    change_4w: float = Field(
        default=0.0,
        description="4-week absolute change in vol index. Positive = rising stress",
    )


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


class VIXTermStructureSnapshot(StalenessAware):
    """VIX front (spot) vs VXV (3-month forward).

    contango (3m > front) = 정상 우상향 곡선, 시장은 calm 현재 stress가 멀리 있다고 봄
    backwardation (front > 3m) = 현재 패닉, 향후 진정 기대 → 위기/recession 신호
    """
    vix_front: float = Field(ge=0)
    vix_3m: float = Field(ge=0)
    ratio: float = Field(description="vix_3m / vix_front; >1.05 contango, <0.95 backwardation")
    regime: Literal["contango", "flat", "backwardation"] = Field(
        description="contango>1.05, flat 0.95~1.05, backwardation<0.95"
    )


class SkewSnapshot(StalenessAware):
    """CBOE SKEW Index. 100 = standard normal distrib. 외가격 풋 헷지 수요 measure.

    역사 평균 ~118. >130 = elevated tail hedge demand. >145 = extreme.
    """
    skew_value: float
    percentile_1y: float = Field(ge=0, le=1)
    tail_hedge_signal: Literal["low", "normal", "elevated", "extreme"] = Field(
        description="<120 low, 120~130 normal, 130~145 elevated, >145 extreme"
    )


class VxnSnapshot(StalenessAware):
    """CBOE NASDAQ-100 Volatility (VXN). 기술주 편중 stress.

    VXN > VIX (양수 spread) = 기술주 stress가 broad market 보다 큼.
    """
    current_value: float = Field(ge=0)
    zscore_30d: float
    percentile_5y: float = Field(ge=0, le=1)
    spread_vs_vix: float = Field(
        description="VXN - VIX. Positive = 기술주 stress > broad. >5 = 의미있는 편중"
    )
