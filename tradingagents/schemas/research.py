"""Stage 2 (Research) 스키마 — 24-cell Cartesian product framework.

설계 동기 (점수 simplex 혼합 문제 해결):
  과거 7-scenario 구조는 "cycle을 가리키는 점 4개" + "modifier 3개"를 같은
  확률 simplex에 욱여넣어 mutually exclusive 가정이 깨졌음 (예: 2017의 goldilocks
  + KR boom 동시 발생을 표현 못 함). 24-cell Cartesian product는 모든 시나리오를
  3축 (cycle × tail × kr) 좌표 한 점으로 정의 → 진짜 직교.

3축 정의:
  D1 cycle (4): A=growth+disinflation, B=growth+inflation,
                 C=recession+disinflation, D=recession+inflation
  D2 tail (2):  N=normal, T=tail (D1 conditional surprise z ≥ +1.0)
  D3 kr (3):    F=follow global, boom=KR outperform, stress=KR underperform

총 24 cell. transient (B-T-*) 3개도 schema에 두되 prompt에서 "very rare" 안내.
"""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


CycleQuadrant = Literal["A", "B", "C", "D"]
TailState = Literal["N", "T"]
KRDirection = Literal["F", "boom", "stress"]

ConvictionLevel = Literal["high", "medium", "low"]

CYCLE_CODES: tuple[CycleQuadrant, ...] = ("A", "B", "C", "D")
TAIL_CODES: tuple[TailState, ...] = ("N", "T")
KR_CODES: tuple[KRDirection, ...] = ("F", "boom", "stress")


def cell_key(cycle: CycleQuadrant, tail: TailState, kr: KRDirection) -> str:
    return f"{cycle}_{tail}_{kr}"


def parse_cell_key(key: str) -> tuple[CycleQuadrant, TailState, KRDirection]:
    parts = key.split("_")
    if len(parts) != 3:
        raise ValueError(f"Invalid cell key: {key}")
    return parts[0], parts[1], parts[2]  # type: ignore[return-value]


ALL_CELLS: tuple[str, ...] = tuple(
    cell_key(c, t, k)
    for c in CYCLE_CODES for t in TAIL_CODES for k in KR_CODES
)
assert len(ALL_CELLS) == 24

# Transient cells — historically rare, transitional states (growth+inflation+tail).
# Schema에는 존재하나 LLM prompt에서 "expect very low P" 안내.
TRANSIENT_CELLS: tuple[str, ...] = tuple(
    cell_key("B", "T", k) for k in KR_CODES
)


class ScenarioProbabilities24(BaseModel):
    """LLM estimator 출력 — 24 cell 확률. 합 = 1.0 ± 0.001 (validator).

    Cell key는 {cycle}_{tail}_{kr} 형식.
    """
    A_N_F: float = Field(ge=0, le=1)
    A_N_boom: float = Field(ge=0, le=1)
    A_N_stress: float = Field(ge=0, le=1)
    A_T_F: float = Field(ge=0, le=1)
    A_T_boom: float = Field(ge=0, le=1)
    A_T_stress: float = Field(ge=0, le=1)

    B_N_F: float = Field(ge=0, le=1)
    B_N_boom: float = Field(ge=0, le=1)
    B_N_stress: float = Field(ge=0, le=1)
    B_T_F: float = Field(ge=0, le=1)
    B_T_boom: float = Field(ge=0, le=1)
    B_T_stress: float = Field(ge=0, le=1)

    C_N_F: float = Field(ge=0, le=1)
    C_N_boom: float = Field(ge=0, le=1)
    C_N_stress: float = Field(ge=0, le=1)
    C_T_F: float = Field(ge=0, le=1)
    C_T_boom: float = Field(ge=0, le=1)
    C_T_stress: float = Field(ge=0, le=1)

    D_N_F: float = Field(ge=0, le=1)
    D_N_boom: float = Field(ge=0, le=1)
    D_N_stress: float = Field(ge=0, le=1)
    D_T_F: float = Field(ge=0, le=1)
    D_T_boom: float = Field(ge=0, le=1)
    D_T_stress: float = Field(ge=0, le=1)

    reasoning: str = Field(
        max_length=1500,
        description="cycle/tail/kr axis별 evidence + dominant cell 근거 ≤1500자",
    )

    @model_validator(mode="after")
    def _sum_to_one(self):
        # 24-dim categorical 에서 LLM 의 sum-to-1 정확도 한계. tol 0.005 일 때
        # ablation perturb 67% / no_macro 33% 실패 (artifacts/2026-05-20/ablation/
        # summary.md). tol 0.02 로 완화 — sum way off (0.5/1.5) 는 여전히 거름.
        # downstream map_probs_to_bucket 이 _renormalize 로 정확한 합 보장.
        # (Issue #9 caveat 후속, C5 regen unblock)
        total = sum(self.as_dict().values())
        if abs(total - 1.0) > 2e-2:
            raise ValueError(f"Cell probabilities must sum to 1.0 ± 0.02, got {total}")
        return self

    def as_dict(self) -> dict[str, float]:
        return {key: getattr(self, key) for key in ALL_CELLS}

    def cycle_marginal(self, cycle: CycleQuadrant) -> float:
        """D1 marginal probability for given cycle."""
        return sum(
            getattr(self, cell_key(cycle, t, k))
            for t in TAIL_CODES for k in KR_CODES
        )

    def tail_marginal(self, tail: TailState) -> float:
        """D2 marginal."""
        return sum(
            getattr(self, cell_key(c, tail, k))
            for c in CYCLE_CODES for k in KR_CODES
        )

    def kr_marginal(self, kr: KRDirection) -> float:
        """D3 marginal."""
        return sum(
            getattr(self, cell_key(c, t, kr))
            for c in CYCLE_CODES for t in TAIL_CODES
        )


# Backward-compat alias (이전 7-scenario 코드 잔재 정리 중 import 에러 방지용).
# 새 코드는 ScenarioProbabilities24 사용.
ScenarioProbabilities = ScenarioProbabilities24


class CellCoord(BaseModel):
    """24 cell의 3-axis 좌표 — dominant_cell 표기/parsing 용."""
    cycle: CycleQuadrant
    tail: TailState
    kr: KRDirection

    @property
    def key(self) -> str:
        return cell_key(self.cycle, self.tail, self.kr)

    @classmethod
    def from_key(cls, key: str) -> "CellCoord":
        c, t, k = parse_cell_key(key)
        return cls(cycle=c, tail=t, kr=k)


# Forward import to avoid circular reference
from tradingagents.schemas.portfolio import BucketTarget  # noqa: E402


class ResearchDecision(BaseModel):
    """Stage 2 종합 출력 — 24-cell framework."""
    bucket_target: BucketTarget
    scenario_probabilities: ScenarioProbabilities24
    dominant_cell: CellCoord                    # max P_cell의 좌표
    dominant_cell_probability: float = Field(ge=0, le=1)
    dominant_cycle: CycleQuadrant               # max D1 marginal cycle
    dominant_cycle_probability: float = Field(ge=0, le=1)
    cycle_marginals: dict[str, float] = Field(
        default_factory=dict, description="cycle code → marginal P, 분석용"
    )
    tail_marginals: dict[str, float] = Field(default_factory=dict)
    kr_marginals: dict[str, float] = Field(default_factory=dict)
    conviction: ConvictionLevel = Field(
        description=(
            "dominant_cycle_probability 기준. "
            "high: ≥0.55, medium: ≥0.35, low: 그 외."
        ),
    )
    # Conviction sharpening (P0 step 3) — cycle marginal에 P^β/Z 적용한 후
    # P(tail, kr | cycle) 보존하며 cell 재구성. β = max(1, 1 + 3(p_dom - 0.30)).
    conviction_beta: float = Field(
        default=1.0, ge=0.5, le=5.0,
        description="P^β/Z sharpening 강도. β=1이면 raw, >1이면 dominant 강화.",
    )
    effective_cycle_marginals: dict[str, float] = Field(
        default_factory=dict,
        description="sharpening 적용 후 cycle 분포. portfolio가 이 값으로 산출됨.",
    )

    # === Factor model fields (Stage 2 factor model PR 2026-05-22) ===
    # PR1: factor model 와 24-cell 가 *공존*. C5 에서 24-cell field 제거.
    # 본 field 는 *defaults empty* — backward-compat.
    factor_scores: dict[str, float] = Field(
        default_factory=dict,
        description="9 factor (F1-F9) 의 z-score. {factor_name: z}",
    )
    factor_contributions: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Factor → bucket contribution (attribution). "
                    "{factor_name: {bucket_name: pp_contribution}}",
    )
    baseline_bucket: dict[str, float] = Field(
        default_factory=dict,
        description="Calibration 의 baseline bucket weight. attribution 용.",
    )
    safety_diagnostics: dict[str, object] = Field(
        default_factory=dict,
        description="Projection audit trail. apply_factor_model_with_safety 의 출력. "
                    "Stage 6 narrative + monitoring 용.",
    )

    @property
    def dominant_scenario(self) -> str:
        """Legacy compat — 7-scenario 이름 추정 (downstream method_picker 등 string 매칭).

        Issue #7 fix: B(growth+inflation) was previously mis-labeled as "stagflation",
        triggering RISK_PARITY defensive in 2026-05-15 run (GDPNow 4.0%, dominant_cycle=B).
        B 는 1972/2021H2 의 overheating regime — equity tilt 유지 + 분산 (HRP) 가 적절.

        매핑 우선순위:
          1. tail marginal ≥ 0.30 → global_credit
          2. kr_marginal[stress] ≥ 0.30 → kr_stress
          3. kr_marginal[boom]  ≥ 0.30 → kr_boom
          4. dominant_cycle:
               A → goldilocks
               B → overheating   (growth+inflation; ≠ stagflation)
               C → broad_recession
               D → stagflation   (recession+inflation; the real stagflation)
        """
        if self.tail_marginals.get("T", 0.0) >= 0.30:
            return "global_credit"
        if self.kr_marginals.get("stress", 0.0) >= 0.30:
            return "kr_stress"
        if self.kr_marginals.get("boom", 0.0) >= 0.30:
            return "kr_boom"
        cycle = self.dominant_cycle
        if cycle == "A":
            return "goldilocks"
        if cycle == "B":
            return "overheating"
        if cycle == "C":
            return "broad_recession"
        # cycle == "D"
        return "stagflation"
