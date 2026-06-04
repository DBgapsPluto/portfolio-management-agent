"""Tier 3 LLM overlay schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


BucketDirection = Literal["increase", "neutral", "decrease"]

LLM_OVERLAY_BUCKETS: tuple[str, ...] = (
    "kr_equity",
    "global_equity",
    "precious_metals",
    "cyclical_commodity_fx",
    "kr_bond",
    "credit",
    "global_duration",
    "cash_mmf",
)

BaseScenario = Literal[
    "goldilocks",
    "overheating",
    "late_cycle",
    "stagflation",
    "broad_recession",
    "global_credit",
    "kr_stress",
    "kr_boom",
    "ai_concentration",
]

NarrativeOverlay = Literal[
    "duration_shock",
    "equity_bond_hedge_failure",
    "ai_concentration",
    "china_reflation",
    "china_stress",
    "valuation_extreme",
    "earnings_confirmation",
    "kr_flow_pressure",
    "policy_surprise",
]


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


class Stage2NarrativeView(BaseModel):
    """LLM narrative policy view for Stage 2.

    The model emits bounded directional tilts, not portfolio weights. Missing
    buckets are treated as neutral by downstream blending; unknown buckets are
    rejected so prompt injection cannot smuggle a new allocation target.
    """
    base_scenario: BaseScenario
    overlays: list[NarrativeOverlay] = Field(default_factory=list, max_length=5)
    bucket_deltas: dict[str, float] = Field(
        default_factory=dict,
        description="Bucket → directional tilt in [-1, +1], not a target weight.",
    )
    risk_budget_delta: float = Field(
        default=0.0, ge=-1.0, le=1.0,
        description="Directional risk-asset budget tilt in [-1, +1].",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, max_length=6)
    expiry_days: int = Field(default=3, ge=1, le=10)
    conflict_with_quant: bool = False
    reasoning: str = Field(max_length=700)

    @field_validator("bucket_deltas")
    @classmethod
    def _validate_bucket_deltas(cls, value: dict[str, float]) -> dict[str, float]:
        allowed = set(LLM_OVERLAY_BUCKETS)
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown bucket(s): {sorted(unknown)}")
        for bucket, delta in value.items():
            if not -1.0 <= float(delta) <= 1.0:
                raise ValueError(f"{bucket} delta must be in [-1, +1]")
        return {bucket: float(delta) for bucket, delta in value.items()}


class Stage3CandidateBoostView(BaseModel):
    """LLM candidate re-rank view for Stage 3.

    The view is intentionally score-only. It cannot add new tickers to the
    universe and cannot set expected returns, covariance, or final weights.
    """
    ticker_boosts: dict[str, float] = Field(default_factory=dict)
    subcategory_boosts: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, max_length=6)
    reasoning: str = Field(max_length=700)

    @field_validator("ticker_boosts", "subcategory_boosts")
    @classmethod
    def _validate_boosts(cls, value: dict[str, float]) -> dict[str, float]:
        for key, boost in value.items():
            if not -1.0 <= float(boost) <= 1.0:
                raise ValueError(f"{key} boost must be in [-1, +1]")
        return {key: float(boost) for key, boost in value.items()}

    def filtered_ticker_boosts(self, allowed_tickers: set[str]) -> dict[str, float]:
        """Return only boosts for tickers already present in the quant longlist."""
        return {
            ticker: boost
            for ticker, boost in self.ticker_boosts.items()
            if ticker in allowed_tickers
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
