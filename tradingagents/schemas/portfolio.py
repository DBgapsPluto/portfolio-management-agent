from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OptimizationMethod(str, Enum):
    HRP = "hrp"
    RISK_PARITY = "risk_parity"
    MIN_VARIANCE = "min_variance"
    BLACK_LITTERMAN = "black_litterman"
    NCO = "nco"   # Phase 3a (2026-05-30)
    AUM_WEIGHTED = "aum_weighted"   # Stage 2/3 merge (2026-06-02): trader bucket + AUM within-bucket


class BucketTarget(BaseModel):
    """Asset class weight target from Research Manager — 14-bucket scheme.

    Each ETF is assigned to exactly one of the 14 buckets defined in the universe.
    Risk is computed per-ETF from the universe bucket label, not from a bucket-level
    property. Pass weights as a dict of bucket_name → weight summing to 1.0.
    """
    weights: dict[str, float] = Field(
        description="Bucket name → weight. 14-bucket scheme."
    )
    rationale: str = Field(max_length=500)

    # --- dict-like accessors so callers can use bucket_target["kr_equity"] etc. ---
    def __getitem__(self, key: str) -> float:
        return self.weights[key]

    def __iter__(self):
        return iter(self.weights)

    def items(self):
        return self.weights.items()

    def keys(self):
        return self.weights.keys()

    def values(self):
        return self.weights.values()

    def get(self, key: str, default=None):
        return self.weights.get(key, default)

    @model_validator(mode="after")
    def _sum_to_one(self):
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Bucket weights must sum to 1.0, got {total}")
        return self

    @property
    def total(self) -> float:
        return sum(self.weights.values())


class CandidateSet(BaseModel):
    """Allocator의 후보 ETF 풀."""
    bucket_to_tickers: dict[str, list[str]]
    selection_criteria: str = Field(max_length=300)
    total_candidates: int = Field(ge=1)


class WeightVector(BaseModel):
    """Allocator의 최종 weight."""
    method: OptimizationMethod
    weights: dict[str, float] = Field(min_length=1, description="ticker → weight")
    rationale: str = Field(max_length=500)
    expected_volatility: float | None = Field(default=None, ge=0)
    expected_sharpe: float | None = None

    @model_validator(mode="after")
    def _normalize(self):
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"Weights must sum to ~1.0, got {total}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("Negative weights not allowed")
        return self


class BucketAllocation(BaseModel):
    """Trader step A 출력 — 14-bucket 비중 (정규화 전 raw 허용)."""
    weights: dict[str, float] = Field(description="14-bucket key → weight")
    rationale: str = Field(default="", max_length=500)


class StockSelection(BaseModel):
    """Trader step B 출력 — bucket key → 선정 ticker 리스트."""
    selections: dict[str, list[str]] = Field(description="bucket key → [ticker]")
    rationale: str = Field(default="", max_length=500)


class BucketRanking(BaseModel):
    """버킷 상대순위 view (BL). LLM 은 tier·conviction 만, 수익숫자는 코드가 변환."""
    tier: Literal["strong_OW", "OW", "neutral", "UW", "strong_UW"]
    conviction: float = Field(ge=0.0, le=0.95)
    rationale: str = Field(default="", max_length=200)


class BucketTilt(BaseModel):
    """Trader step A 출력 — quadrant 앵커 대비 버킷별 tilt (sparse, 미지정=0)."""
    tilts: dict[str, float] = Field(
        default_factory=dict,
        description="bucket key → 앵커 대비 가감(+/-). 오버웨이트는 언더웨이트로 펀딩(net≈0).",
    )
    sub_category_views: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="이질 버킷 한정 — bucket key → {sub_category: 선호 ∈ [-1,+1]}. +선호/-배제/0중립.",
    )
    bucket_ranking: dict[str, BucketRanking] = Field(
        default_factory=dict,
        description="bucket key → 상대순위 view (BL). tier+conviction.",
    )
    rationale: str = Field(default="", max_length=500)
