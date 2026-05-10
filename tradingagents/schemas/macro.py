from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from tradingagents.schemas._base import StalenessAware


RegimeQuadrant = Literal[
    "growth_inflation",
    "growth_disinflation",
    "recession_inflation",
    "recession_disinflation",
]


class YieldCurveSnapshot(StalenessAware):
    spread_10y_2y_bps: float = Field(description="10Y - 2Y in basis points")
    spread_10y_3m_bps: float = Field(description="10Y - 3M in basis points")
    inverted_days_count: int = Field(ge=0, description="Days inverted in last 365")
    percentile_5y: float = Field(ge=0, le=1, description="5y historical percentile")


class InflationSnapshot(StalenessAware):
    cpi_yoy: float = Field(description="CPI YoY %")
    core_cpi_yoy: float = Field(description="Core CPI YoY %")
    momentum_3mo: float = Field(description="3-month annualized rate")
    momentum_6mo: float = Field(description="6-month annualized rate")
    accelerating: bool = Field(description="True if 3mo > 6mo > 12mo")


class EmploymentSnapshot(StalenessAware):
    unemployment_rate: float
    rate_change_3mo: float = Field(description="3-month change in UR")
    sahm_rule_triggered: bool = Field(description="Sahm rule recession indicator")
    non_farm_payrolls_3mo_avg: float


class DivergenceScore(StalenessAware):
    us_kr_rate_gap_bps: float = Field(description="US policy rate - KR base rate")
    us_kr_inflation_gap: float
    score: float = Field(ge=-10, le=10, description="Negative = divergence, positive = convergence")


class CentralBankEvent(BaseModel):
    """Not StalenessAware — calendar events are forward-looking."""
    bank: Literal["FED", "BOK", "ECB", "BOJ", "PBOC"]
    event_date: date
    event_type: Literal["rate_decision", "minutes", "speech", "press_conference"]
    description: str = Field(max_length=200)


class RegimeClassification(StalenessAware):
    """Subagent output — schema-locked."""
    quadrant: RegimeQuadrant
    confidence: float = Field(ge=0, le=1)
    drivers: list[str] = Field(min_length=1, max_length=5)
    reasoning: str = Field(max_length=300)
