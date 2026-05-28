from pydantic import BaseModel, Field

from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    DivergenceScore, RegimeClassification, CentralBankEvent,
    KRExportSnapshot, KRLeadingIndexSnapshot, KRBusinessSurveySnapshot,
    USLeadingIndexSnapshot, GDPNowSnapshot,
    FinancialConditionsSnapshot, InflationExpectationsSnapshot, FedPathSnapshot,
    FXSnapshot, RiskAppetiteSnapshot, ChinaLeadingSnapshot, ForeignFlowSnapshot,
    PolicyUncertaintySnapshot, TailRiskSnapshot, KRValuationSnapshot,
    CommodityMomentumSnapshot, USEquityValuationSnapshot,
    GeopoliticalRiskSnapshot, ChinaCreditImpulseSnapshot,
    EarningsRevisionSnapshot,
)
from tradingagents.schemas.risk import (
    VolatilitySnapshot, SpreadSnapshot, SentimentSnapshot,
    BreadthSnapshot, PCASnapshot, SystemicRiskScore,
    VIXTermStructureSnapshot, SkewSnapshot, VxnSnapshot,
    RealYieldsSnapshot, FundingStressSnapshot, CreditQualitySnapshot,
    KRYieldCurveSnapshot, KRCorpSpreadSnapshot, KRMarginDebtSnapshot,
    KRMarketTierSnapshot, EquityBondCorrelationSnapshot,
    RealVolSnapshot, ExcessBondPremiumSnapshot,
)
from tradingagents.schemas.technical import (
    IndicatorPanel, TrendState, ETFRanking, Cluster,
    ExtendedIndicatorPanel, TrendQuantification,
    UniverseBreadthSnapshot, SectorRotationSnapshot,
    RiskAdjustedMetrics,
)
from tradingagents.schemas.news import (
    CalendarEvent, RankedNews, GlobalOvernightSnapshot,
    ReleaseSurpriseSnapshot, NewsSentimentSnapshot,
    SpeakerToneAggregate, SaveBriefSnapshot,
)
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
    # Tier-1 확장 (KR cycle + US 선행/실시간 성장)
    kr_export: KRExportSnapshot
    kr_leading: KRLeadingIndexSnapshot
    kr_business_survey: KRBusinessSurveySnapshot
    us_leading: USLeadingIndexSnapshot
    gdp_nowcast: GDPNowSnapshot
    # Tier-2 확장 (Financial conditions + 기대인플레 + Fed path)
    financial_conditions: FinancialConditionsSnapshot
    inflation_expectations: InflationExpectationsSnapshot
    fed_path: FedPathSnapshot
    # Tier-3 확장 (Cross-asset + KR FX overlay)
    fx: FXSnapshot
    risk_appetite: RiskAppetiteSnapshot
    china_leading: ChinaLeadingSnapshot
    foreign_flow: ForeignFlowSnapshot
    # Tier-4 확장 (Policy uncertainty + Tail risk)
    policy_uncertainty: PolicyUncertaintySnapshot
    tail_risk: TailRiskSnapshot
    # 2026-05-23 C5 — KR equity valuation for factor model F8 valuation.
    # Optional / default None — backward compat (기존 archive 호환).
    kr_valuation: KRValuationSnapshot | None = None
    # === Tier 0 (2026-05-28) — Optional new snapshots ===
    commodity_momentum: CommodityMomentumSnapshot | None = None
    us_equity_valuation: USEquityValuationSnapshot | None = None
    geopolitical_risk: GeopoliticalRiskSnapshot | None = None
    china_credit_impulse: ChinaCreditImpulseSnapshot | None = None
    earnings_revision: EarningsRevisionSnapshot | None = None
    # === Tier 0 F1 reform — INDPRO YoY + Real PCE YoY ===
    us_indpro_yoy_pct: float | None = None
    us_real_pce_yoy_pct: float | None = None


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
    # Tier-1 확장 (Equity stress 깊이)
    vix_term: VIXTermStructureSnapshot
    skew: SkewSnapshot
    vxn: VxnSnapshot
    # Tier-2 확장 (Bond/funding stress)
    real_yields: RealYieldsSnapshot
    funding_stress: FundingStressSnapshot
    credit_quality: CreditQualitySnapshot
    # Tier-3 확장 (KR-specific risk)
    kr_yield_curve: KRYieldCurveSnapshot
    kr_corp_spread: KRCorpSpreadSnapshot
    kr_margin_debt: KRMarginDebtSnapshot
    kr_market_tier: KRMarketTierSnapshot
    # Tier-4 확장 (Cross-asset positioning + 개선)
    equity_bond_corr: EquityBondCorrelationSnapshot
    # 주: PCA는 기존 correlation_concentration 필드 사용 (real returns로 wire만 변경)
    # 2026-05-23 C6 — SPY realized vol for factor model F7 + F9 (via VRP).
    # Optional / default None — backward compat (기존 archive 호환).
    real_vol: RealVolSnapshot | None = None
    # === Tier 0 (2026-05-28) ===
    excess_bond_premium: ExcessBondPremiumSnapshot | None = None


class TechnicalReport(_AnalystReport):
    asset_class_momentum: dict[str, list[ETFRanking]] = Field(
        description="Category name → top-N ETFs"
    )
    individual_etf_states: dict[str, TrendState]
    # SCOPE: top-tier ETF subset only (analyst filters before calling
    # find_correlation_clusters), 252d window, threshold ≥ 0.7. Used by
    # mandate_validator + risk_judge for concentration checks.
    # Distinct from `sector_rotation.correlation_*` which spans the full
    # universe (188 ETF, 60d/252d median) — different scope, different question.
    correlation_clusters: list[Cluster]
    factor_panel: dict[str, FactorPanel] = Field(
        default_factory=dict,
        description="Ticker → raw factor values (skip-1m mom, vol, Sharpe, log AUM). "
                    "Consumed by Stage 3 candidate selector for z-score + regime blend.",
    )
    # Tier-1 확장 (Indicator 깊이) — 188 ETF 전체 ExtendedIndicatorPanel.
    # LLM(summary)에는 집계만 노출, 객체 자체는 Stage 3 allocator용.
    extended_indicators: dict[str, ExtendedIndicatorPanel] = Field(
        default_factory=dict,
        description="Ticker → Bollinger/ADX/Stochastic/Volume/Divergence/Weekly panel.",
    )
    # Tier-2 확장 (Trend 정량화)
    trend_quantification: dict[str, TrendQuantification] = Field(
        default_factory=dict,
        description="Ticker → trend_strength/time-in-state/dual momentum/acceleration.",
    )
    # Tier-3 확장 (Universe breadth) — 단일 snapshot.
    universe_breadth: UniverseBreadthSnapshot | None = Field(
        default=None,
        description="188 ETF aggregate: %above MA, 52w hi/lo, A/D, vol regime.",
    )
    # Tier-4 확장 (Sector rotation + correlation regime)
    sector_rotation: SectorRotationSnapshot | None = Field(
        default=None,
        description="카테고리 leadership matrix + spread + 60d/252d corr regime.",
    )
    # Tier-5 확장 (Risk-adjusted, 188 ETF)
    risk_adjusted: dict[str, RiskAdjustedMetrics] = Field(
        default_factory=dict,
        description="Ticker → Sortino/Calmar/skew/kurt/reversion candidate.",
    )


class NewsReport(_AnalystReport):
    upcoming_events: list[CalendarEvent]
    ranked_news: list[RankedNews]
    # Tier-1 확장 (Global overnight — 이전 분석가가 안 보는 차원)
    global_overnight: GlobalOvernightSnapshot | None = Field(
        default=None,
        description="STOXX50/FTSE/N225/HSI/SSE/TWII/WTI/NG/USDKRW overnight. "
                    "US 데이터는 macro_quant/market_risk가 커버.",
    )
    # Tier-2 확장 (Release surprise — forecast vs actual)
    release_surprise: ReleaseSurpriseSnapshot | None = Field(
        default=None,
        description="경제지표 surprise + 30d ESI bias. macro_quant FRED actual "
                    "라인이 못 잡는 forecast 대비 차이.",
    )
    # Tier-3 확장 (News categorizer + sentiment + momentum)
    news_sentiment: NewsSentimentSnapshot | None = Field(
        default=None,
        description="5분류 카테고리별 count·sentiment·top headline + 24h vs 7d momentum.",
    )
    # Tier-4 확장 (Central Bank speaker tone tracker)
    cb_speakers: SpeakerToneAggregate | None = Field(
        default=None,
        description="Fed/BOK/ECB/BOJ 7d 매파-비둘기 balance. voting members 별도 가중.",
    )
    # Tier-5 확장 (SAVE 브리핑 ingestor — Tier-2/3/event 보강용)
    save_brief: SaveBriefSnapshot | None = Field(
        default=None,
        description="SAVE 평일 브리핑에서 큐레이션된 release/news cards/weekly schedule.",
    )
