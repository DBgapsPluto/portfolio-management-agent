from enum import Enum

from pydantic import BaseModel, Field, model_validator


class OptimizationMethod(str, Enum):
    HRP = "hrp"
    RISK_PARITY = "risk_parity"
    MIN_VARIANCE = "min_variance"
    BLACK_LITTERMAN = "black_litterman"
    NCO = "nco"   # Phase 3a (2026-05-30)


class BucketTarget(BaseModel):
    """Asset class weight target from Research Manager."""
    kr_equity: float = Field(ge=0, le=1)
    global_equity: float = Field(ge=0, le=1)
    fx_commodity: float = Field(ge=0, le=1)
    bond: float = Field(ge=0, le=1)
    cash_mmf: float = Field(ge=0, le=1)
    rationale: str = Field(max_length=500)
    # Within the bond bucket, fraction allocated to inflation-linked candidates
    # (sub_category="inflation_linked"). Nominal candidates take the remainder.
    # Default 0.0 keeps legacy fixtures valid; mapper overrides at runtime.
    bond_tips_share: float = Field(default=0.0, ge=0, le=1)

    @property
    def total(self) -> float:
        return self.kr_equity + self.global_equity + self.fx_commodity + self.bond + self.cash_mmf

    @model_validator(mode="after")
    def _sum_to_one(self):
        if abs(self.total - 1.0) > 1e-6:
            raise ValueError(f"Bucket weights must sum to 1.0, got {self.total}")
        return self

    @property
    def risk_asset_weight(self) -> float:
        """위험자산 합계 (대회 §2.2 룰: ≤70%)."""
        return self.kr_equity + self.global_equity + self.fx_commodity


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
