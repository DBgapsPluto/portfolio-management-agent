from pydantic import BaseModel, Field

from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    DivergenceScore, RegimeClassification, CentralBankEvent,
)
from tradingagents.schemas.risk import (
    VolatilitySnapshot, SpreadSnapshot, SentimentSnapshot,
    BreadthSnapshot, PCASnapshot, SystemicRiskScore,
)
from tradingagents.schemas.technical import (
    IndicatorPanel, TrendState, ETFRanking, Cluster,
)
from tradingagents.schemas.news import CalendarEvent, RankedNews
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


# 공통: 모든 분석가 출력은 narrative ≤500 + summary_for_downstream ≤2000
NARRATIVE_MAX = 500
SUMMARY_MAX = 2000


class _AnalystReport(BaseModel):
    narrative: str = Field(max_length=NARRATIVE_MAX, description="LLM-authored prose; data must come from skill outputs")
    summary_for_downstream: str = Field(
        max_length=SUMMARY_MAX,
        description="Markdown summary handoff to next stage (D2 hybrid topology)",
    )


class MacroReport(_AnalystReport):
    yield_curve: YieldCurveSnapshot
    inflation: InflationSnapshot
    employment: EmploymentSnapshot
    kr_divergence: DivergenceScore
    regime: RegimeClassification
    upcoming_events: list[CentralBankEvent]


class RiskReport(_AnalystReport):
    vix: VolatilitySnapshot
    vkospi: VolatilitySnapshot
    credit_spread_us_ig: SpreadSnapshot
    credit_spread_us_hy: SpreadSnapshot
    fear_greed: SentimentSnapshot
    breadth_kr: BreadthSnapshot
    breadth_us: BreadthSnapshot
    correlation_concentration: PCASnapshot
    systemic_score: SystemicRiskScore


class TechnicalReport(_AnalystReport):
    asset_class_momentum: dict[str, list[ETFRanking]] = Field(
        description="Category name → top-N ETFs"
    )
    individual_etf_states: dict[str, TrendState]
    correlation_clusters: list[Cluster]
    factor_panel: dict[str, FactorPanel] = Field(
        default_factory=dict,
        description="Ticker → raw factor values (skip-1m mom, vol, Sharpe, log AUM). "
                    "Consumed by Stage 3 candidate selector for z-score + regime blend.",
    )


class NewsReport(_AnalystReport):
    upcoming_events: list[CalendarEvent]
    ranked_news: list[RankedNews]
