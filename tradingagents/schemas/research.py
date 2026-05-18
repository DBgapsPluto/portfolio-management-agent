"""Stage 2 (Research) 스키마 — 시나리오 확률 기반 의사결정.

폐기: Bull/Bear advocacy (ResearcherTurn). 토론 구조는 motivated reasoning을
유발하고 진짜 disagreement 측정을 못 함. 대체:
  estimator가 7개 직교 시나리오 확률을 추정 → 결정적 매핑이 BucketTarget 산출.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from tradingagents.schemas.portfolio import BucketTarget


# 7개 직교 시나리오 — 4차원 (글로벌 cycle / breadth / credit / KR cycle) 조합
ScenarioName = Literal[
    "goldilocks",         # A: growth + disinflation, broad
    "ai_concentration",   # B: growth + disinflation, narrow (mega-cap rally)
    "stagflation",        # C: inflation 끈끈 + 성장 둔화
    "broad_recession",    # D: recession + disinflation, broad-down
    "global_credit",      # E: credit event (HY spike, systemic risk)
    "kr_boom",            # F: KR 단독 decoupling boom (수출 cycle ↑)
    "kr_stress",          # G: KR-specific stress (레고랜드형, 부동산 PF)
]

ConvictionLevel = Literal["high", "medium", "low"]


class ScenarioProbabilities(BaseModel):
    """LLM estimator 출력 — 7개 시나리오 확률 (합 = 1.0)."""
    goldilocks: float = Field(ge=0, le=1)
    ai_concentration: float = Field(ge=0, le=1)
    stagflation: float = Field(ge=0, le=1)
    broad_recession: float = Field(ge=0, le=1)
    global_credit: float = Field(ge=0, le=1)
    kr_boom: float = Field(ge=0, le=1)
    kr_stress: float = Field(ge=0, le=1)
    reasoning: str = Field(max_length=800, description="시나리오별 evidence 근거 ≤800자")

    @model_validator(mode="after")
    def _sum_to_one(self):
        total = (
            self.goldilocks + self.ai_concentration + self.stagflation
            + self.broad_recession + self.global_credit
            + self.kr_boom + self.kr_stress
        )
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"Scenario probabilities must sum to 1.0, got {total}")
        return self

    def as_dict(self) -> dict[ScenarioName, float]:
        return {
            "goldilocks": self.goldilocks,
            "ai_concentration": self.ai_concentration,
            "stagflation": self.stagflation,
            "broad_recession": self.broad_recession,
            "global_credit": self.global_credit,
            "kr_boom": self.kr_boom,
            "kr_stress": self.kr_stress,
        }


class ResearchDecision(BaseModel):
    """Stage 2 종합 출력 — Stage 3/4/5는 bucket_target만 봐도 OK,
    리포트와 Stage 4 Risk Judge는 scenario/conviction 활용 가능."""
    bucket_target: BucketTarget
    scenario_probabilities: ScenarioProbabilities
    dominant_scenario: ScenarioName
    dominant_probability: float = Field(ge=0, le=1)
    conviction: ConvictionLevel = Field(
        description="high: max_prob≥0.45, medium: ≥0.30, low: else",
    )
