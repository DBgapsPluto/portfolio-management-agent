"""Tier 3 LLM overlay schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


BucketDirection = Literal["increase", "neutral", "decrease"]


class LLMBucketView(BaseModel):
    """Single LLM forward output — directional bucket view.

    Per-bucket delta in [-1, +1]:
      +1 = strongly increase from quant baseline
       0 = neutral
      -1 = strongly decrease
    """
    kr_equity:             float = Field(ge=-1.0, le=1.0)
    global_equity:         float = Field(ge=-1.0, le=1.0)
    precious_metals:       float = Field(ge=-1.0, le=1.0)
    cyclical_commodity_fx: float = Field(ge=-1.0, le=1.0)
    kr_bond:               float = Field(ge=-1.0, le=1.0)
    credit:                float = Field(ge=-1.0, le=1.0)
    global_duration:       float = Field(ge=-1.0, le=1.0)
    cash_mmf:              float = Field(ge=-1.0, le=1.0)

    confidence: float = Field(ge=0.0, le=1.0, description="LLM self-rated confidence")
    reasoning: str = Field(max_length=500)
    cited_events: list[str] = Field(default_factory=list, max_length=5)

    def to_delta_dict(self) -> dict[str, float]:
        return {
            "kr_equity": self.kr_equity,
            "global_equity": self.global_equity,
            "precious_metals": self.precious_metals,
            "cyclical_commodity_fx": self.cyclical_commodity_fx,
            "kr_bond": self.kr_bond,
            "credit": self.credit,
            "global_duration": self.global_duration,
            "cash_mmf": self.cash_mmf,
        }


class CredibilityState(BaseModel):
    """Per-bucket LLM credibility (EWMA, persisted)."""
    bucket_cred: dict[str, float] = Field(default_factory=dict)
    history_count: int = 0
    last_updated: date


class LLMOverlayJournal(BaseModel):
    """Per-rebalance LLM overlay journal entry for forward-tuning."""
    timestamp: datetime
    quant_target: dict[str, float]
    llm_views: list[LLMBucketView]
    novelty: float
    consensus: dict[str, float]
    credibility_snapshot: dict[str, float]
    final_target: dict[str, float]
    audit: dict[str, dict[str, float]]
    realized_returns: dict[str, float] | None = None
