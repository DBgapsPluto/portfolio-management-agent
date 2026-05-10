from typing import Literal

from pydantic import BaseModel, Field


class Violation(BaseModel):
    rule: Literal[
        "universe_membership",
        "risk_asset_cap",      # 70%
        "single_etf_cap",      # 20%
        "turnover_floor",
        "correlation_concentration",
    ]
    description: str = Field(max_length=500)
    severity: Literal["hard", "soft"]
    suggested_fix: str = Field(max_length=300)


class ValidationReport(BaseModel):
    passed: bool
    violations: list[Violation]
    suggestions: list[str] = Field(default_factory=list)

    @property
    def has_hard_violations(self) -> bool:
        return any(v.severity == "hard" for v in self.violations)

    @property
    def hard_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "hard"]
