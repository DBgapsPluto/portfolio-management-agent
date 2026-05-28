from enum import Enum

from pydantic import BaseModel, Field, model_validator


class OptimizationMethod(str, Enum):
    HRP = "hrp"
    RISK_PARITY = "risk_parity"
    MIN_VARIANCE = "min_variance"
    BLACK_LITTERMAN = "black_litterman"


class BucketTarget(BaseModel):
    """Asset class weight target from Research Manager — 8-bucket schema (Tier 1).

    Buckets (8): kr_equity, global_equity, precious_metals,
                 cyclical_commodity_fx, kr_bond, credit, global_duration, cash_mmf.

    Legacy 5-bucket names (fx_commodity, bond) are no longer valid fields; all
    callers must pass the 8-bucket dict.

    bond_tips_share: fraction of bond-equivalent buckets (kr_bond + credit +
        global_duration) allocated to inflation-linked candidates. Stored separately
        from weights so the candidate selector can split the pool.
    """
    weights: dict[str, float] = Field(
        description="Bucket name → weight. 8-bucket schema (Tier 1)."
    )
    rationale: str = Field(max_length=500)
    bond_tips_share: float = Field(default=0.0, ge=0, le=1)

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

    @property
    def risk_asset_weight(self) -> float:
        """위험자산 합계 (대회 §2.2 룰: ≤70%).

        Risk buckets: kr_equity, global_equity, precious_metals,
                      cyclical_commodity_fx.
        """
        _RISK = ("kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx")
        return sum(self.weights.get(b, 0.0) for b in _RISK)


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
