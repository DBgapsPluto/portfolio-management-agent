"""Bull/Bear researcher per-turn schema — used by the confidence-based
adaptive-rounds logic in the research_debate sub-graph."""
from pydantic import BaseModel, Field


class ResearcherTurn(BaseModel):
    """One Bull or Bear contribution within a debate round."""

    argument: str = Field(max_length=600, description="Argument text in Korean, ≤400 chars")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Self-reported confidence that this side's position is correct (0..1)",
    )
    proposed_risk_tilt: float = Field(
        ge=0.0, le=1.0,
        description=(
            "Proposed risk-asset weight in [0, 1]. Bull typically high (>=0.6), "
            "Bear typically low (<=0.4). Used to measure divergence between sides."
        ),
    )
