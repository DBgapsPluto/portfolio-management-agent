from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from tradingagents.schemas._base import StalenessAware


AssetClass = Literal[
    "kr_equity", "us_equity", "global_equity",
    "kr_bond", "us_bond",
    "fx", "commodity", "gold",
]


class CalendarEvent(BaseModel):
    event_date: date
    region: Literal["US", "KR", "EU", "JP", "CN", "GLOBAL"]
    event_type: Literal["fomc", "bok", "cpi", "gdp", "employment", "pmi", "other"]
    description: str = Field(max_length=200)
    consensus: str | None = Field(default=None, max_length=80)


class NewsItem(BaseModel):
    headline: str = Field(max_length=300)
    source: str
    published_at: datetime
    url: str  # plain str for resilience to bad sources


class ImpactAssessment(BaseModel):
    """Subagent output."""
    asset_classes_affected: list[AssetClass] = Field(min_length=1, max_length=4)
    direction: Literal["up", "down", "neutral"]
    severity: int = Field(ge=1, le=5)
    reasoning: str = Field(max_length=200)


class RankedNews(BaseModel):
    item: NewsItem
    impact: ImpactAssessment
    rank_score: float = Field(description="severity * recency_weight")


# ---------- Tier-1: Global Overnight (US 제외 — 다른 분석가가 안 보는 차원) ----------


OvernightDirection = Literal["up", "down", "flat"]
OvernightRiskRegime = Literal["risk_on", "risk_off", "mixed"]


class OvernightMove(BaseModel):
    """단일 자산의 overnight 변동 — 전일 종가 대비."""
    name: str = Field(description="친근명 — 'STOXX50', 'N225', 'WTI' 등")
    ticker: str
    value: float = Field(description="최신 종가 (KRW=X면 USDKRW rate)")
    prior: float = Field(description="직전 영업일 종가")
    change_abs: float = Field(description="value - prior")
    change_pct: float = Field(description="(value - prior) / prior * 100. 채권은 0.")
    direction: OvernightDirection


class GlobalOvernightSnapshot(StalenessAware):
    """Tier-1 — 글로벌 overnight (US 제외). 미국은 macro_quant + market_risk가 커버.

    9개 자산: 유럽/일본/홍콩/중국/영국/대만/원유/천연가스/USDKRW.
    한국 개장 전 마지막 글로벌 시그널.
    """
    europe: dict[str, OvernightMove] = Field(
        default_factory=dict, description="STOXX50, FTSE",
    )
    asia: dict[str, OvernightMove] = Field(
        default_factory=dict, description="N225, HSI, SSE, TWII",
    )
    commodities: dict[str, OvernightMove] = Field(
        default_factory=dict, description="WTI, NG (gold는 macro_quant/market_risk)",
    )
    krw: OvernightMove | None = Field(
        default=None, description="USDKRW 야간 (FRED DEXKOUS는 lag 있어서 NEW)",
    )
    risk_regime_overnight: OvernightRiskRegime
    narrative_seed: str = Field(
        max_length=300,
        description="SAVE 스타일 한 줄 — Bull/Bear가 그대로 인용 가능",
    )
    fetched_count: int = Field(ge=0, description="9개 중 fetch 성공 개수")


# ---------- Tier-2: Economic Release Surprise ----------


SurpriseDirection = Literal["positive", "negative", "inline", "unknown"]
ReleaseBias = Literal["hawkish_surprise", "dovish_surprise", "balanced"]


class ReleaseSurprise(BaseModel):
    """단일 경제지표 발표의 예상 vs 실제."""
    release_date: date
    region: Literal["US", "KR", "EU", "JP", "CN", "UK", "GLOBAL"]
    indicator: str = Field(description="'US CPI YoY', 'KR Industrial Production' 등")
    importance: int = Field(ge=1, le=3, description="★ 1~3")
    forecast: float | None
    actual: float | None
    previous: float | None = None
    surprise: float | None = Field(
        default=None, description="actual - forecast (정량 없으면 None)",
    )
    surprise_zscore: float | None = Field(
        default=None,
        description="해당 지표의 historical surprise std로 정규화. 없으면 None.",
    )
    direction: SurpriseDirection
    unit: Literal["pct", "level", "k", "m", "bps"] = Field(
        default="level",
        description="actual 단위 — pct=%, k=천 (실업수당청구), bps=basis point",
    )


class ReleaseSurpriseSnapshot(StalenessAware):
    """Tier-2 — 경제지표 surprise 집계 + ESI 스타일 누적 인덱스.

    forecast/actual의 차이는 macro_quant FRED actual-only 라인에서 안 잡힘 →
    NEW 정보.
    """
    today_releases: list[ReleaseSurprise] = Field(default_factory=list)
    last_5d_releases: list[ReleaseSurprise] = Field(default_factory=list)
    surprise_index_30d: float = Field(
        default=0.0,
        description="최근 30d zscore 평균. + 매크로 우상향, - 우하향.",
    )
    high_importance_today: int = Field(
        ge=0, description="오늘 ★★★ 지표 카운트",
    )
    bias_30d: ReleaseBias = Field(
        default="balanced",
        description="hawkish_surprise: 인플레/고용 강함 (CB 매파 명분), dovish: 약함.",
    )


# ---------- Tier-3: News Categorizer + Sentiment + Momentum ----------


NewsCategory = Literal[
    "policy", "macro", "corporate", "geopolitical", "market_commentary",
]
ClassifierSource = Literal["keyword", "llm"]


class CategorizedNewsItem(BaseModel):
    """뉴스 1건 + 분류·sentiment·확신도."""
    item: NewsItem
    category: NewsCategory
    sentiment_score: float = Field(ge=-1, le=1)
    classifier_source: ClassifierSource = Field(
        description="keyword=비용0 1차 매칭, llm=2차 fallback",
    )


class NewsSentimentSnapshot(StalenessAware):
    """Tier-3 — 카테고리별 sentiment 집계 + momentum (어제 대비)."""
    counts: dict[NewsCategory, int] = Field(default_factory=dict)
    avg_sentiment: dict[NewsCategory, float] = Field(default_factory=dict)
    dominant_category: NewsCategory | None = None
    sentiment_dispersion: float = Field(
        default=0.0, description="카테고리간 avg_sentiment 표준편차 (분열도).",
    )
    top_headline_per_category: dict[NewsCategory, str] = Field(default_factory=dict)
    # Momentum (어제·최근 7일 평균 대비)
    count_change_vs_7d: dict[NewsCategory, float] = Field(
        default_factory=dict,
        description="최근 24h count - 직전 7일 daily mean. +면 이슈 가속.",
    )
    rising_category: NewsCategory | None = Field(
        default=None,
        description="가장 급증한 카테고리. 카운트 2배+면 채워짐.",
    )
