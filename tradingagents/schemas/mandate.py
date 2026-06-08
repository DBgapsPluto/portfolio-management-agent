from typing import Literal

from pydantic import BaseModel, Field


# Rebalance mode — validator의 turnover floor / days 결정에 사용.
# Stage 5 정리에서 explicit Literal로 명시 (이전엔 previous_portfolio 유무로
# implicit 분기만). daily/weekly는 룰북 / 운영자 결정 후 FLOOR_BY_MODE에 추가.
RebalanceMode = Literal["initial", "monthly"]


class Violation(BaseModel):
    rule: Literal[
        "universe_membership",
        "risk_asset_cap",            # 70%
        "single_etf_cap",            # 20%
        "category_cap",              # 세부자산(category)별 상한 (대회 §2.2)
        "turnover_floor",
        "correlation_concentration",
        # Stage 5 정리에서 신설 (Weight integrity 사전 검증)
        "weight_sum",
        "weight_validity",
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
