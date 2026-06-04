"""Stage 2 allocation contract — prior vs feasible bucket weights (Phase 0+)."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from tradingagents.skills.research.factor_to_bucket import BUCKETS


class BucketEnvelope(BaseModel):
    lo: float = Field(ge=0.0, le=1.0)
    hi: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _lo_le_hi(self):
        if self.lo > self.hi + 1e-12:
            raise ValueError(f"envelope lo={self.lo} > hi={self.hi}")
        return self


class ThemeLimit(BaseModel):
    """Max portfolio-wide weight for a sub_category (Stage 3 enforcement in Phase 2)."""

    sub_category: str
    max_portfolio_share: float = Field(ge=0.0, le=1.0)


class InvestabilitySnapshot(BaseModel):
    n_eligible: int = Field(ge=0)
    n_selectable: int = Field(
        default=0,
        ge=0,
        description="Tickers with alpha > 0 (Stage 3 n_positive_alpha rule).",
    )
    max_realizable_weight: float = Field(ge=0.0, le=1.0)
    tickers_sample: list[str] = Field(default_factory=list, max_length=5)


class AllocationContract(BaseModel):
    """Executable macro contract for Stage 3 (envelope solver in Phase 2)."""

    prior_weights: dict[str, float] = Field(
        description="Macro view after quant + Stage 2 LLM (before investability).",
    )
    feasible_weights: dict[str, float] = Field(
        description="Investability-projected weights; drives bucket_target.",
    )
    envelope: dict[str, BucketEnvelope] = Field(
        description="Per-bucket bounds; Phase 0 uses band around feasible center.",
    )
    theme_limits: list[ThemeLimit] = Field(default_factory=list)
    implied_bucket_returns: dict[str, float] = Field(
        default_factory=dict,
        description="Annualized bucket return views for BL (factor-derived in Phase 0).",
    )
    bond_tips_share: float = Field(default=0.0, ge=0, le=1)
    investability: dict[str, InvestabilitySnapshot] = Field(default_factory=dict)
    binding_stage2: dict[str, str] = Field(
        default_factory=dict,
        description="Per-bucket binding reason (thin_universe, capped_realizable, ok, ...).",
    )
    projection_audit: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _weights_complete(self):
        for label, weights in (
            ("prior_weights", self.prior_weights),
            ("feasible_weights", self.feasible_weights),
        ):
            missing = [b for b in BUCKETS if b not in weights]
            if missing:
                raise ValueError(f"{label} missing buckets: {missing}")
            total = sum(weights.values())
            if abs(total - 1.0) > 1e-5:
                raise ValueError(f"{label} must sum to 1.0, got {total}")
        return self
