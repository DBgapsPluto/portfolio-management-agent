from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


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
