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
