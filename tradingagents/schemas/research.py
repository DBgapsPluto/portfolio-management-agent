"""Stage 2 (Research) 스키마 — factor model (PR 2026-05-22).

C5 (2026-05-23) 에서 24-cell Cartesian product framework 완전 제거.
- 제거: ScenarioProbabilities24, CellCoord, ALL_CELLS, TRANSIENT_CELLS,
  cell_key, parse_cell_key, CycleQuadrant, TailState, KRDirection,
  ScenarioProbabilities alias, cycle/tail/kr 관련 marginals.
- 유지: ConvictionLevel, ResearchDecision (factor model 만), dominant_scenario
  *string field* (downstream method_picker / candidate_selector 의 log_boost 가
  legacy scenario name 으로 호출 — *24-cell schema 와 별개* 의 Stage 3 dep).
"""
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, BeforeValidator, Field


ConvictionLevel = Literal["high", "medium", "low"]

ScenarioLabel = Literal[
    "kr_boom", "kr_stress", "global_credit", "ai_concentration", "neutral",
]
_VALID_SCENARIOS = frozenset(get_args(ScenarioLabel))


def _coerce_scenario(v: object) -> object:
    """enum 밖 값(구 라벨/free text) → neutral. replay·구 archive 호환."""
    return v if v in _VALID_SCENARIOS else "neutral"


# 두 모델 공용 — Annotated + BeforeValidator 로 coercion 을 타입에 부착(DRY).
ScenarioField = Annotated[ScenarioLabel, BeforeValidator(_coerce_scenario)]


# Forward import to avoid circular reference
from tradingagents.schemas.portfolio import BucketTarget  # noqa: E402


class ResearchDecision(BaseModel):
    """Stage 2 종합 출력 — factor model.

    Schema 단순화 (C5): 24-cell field (~10개) 제거 → 5 field.
    factor_scores / factor_contributions / baseline_bucket / safety_diagnostics
    + bucket_target / conviction / dominant_scenario.

    `dominant_scenario` 는 legacy scenario name string (goldilocks / overheating
    / broad_recession / stagflation / global_credit / kr_boom / kr_stress) —
    downstream method_picker / candidate_selector 의 log_boost 가 이 string 으로
    BOOST_BY_CYCLE/TAIL/KR table lookup. factor model 의 derive_dominant_scenario
    가 *명시적으로* set (이전 @property 가 marginal 로 derive 하던 path 제거).
    """
    bucket_target: BucketTarget
    conviction: ConvictionLevel = Field(
        description="factor model 의 derive_conviction 결과 (high/medium/low).",
    )
    dominant_scenario: str = Field(
        default="goldilocks",
        description=(
            "Legacy compat — factor model 의 derive_dominant_scenario 가 derive. "
            "downstream method_picker / candidate_selector 의 log_boost 호출에 사용."
        ),
    )

    # === Factor model fields ===
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

    model_config = {
        # 기존 archive (runs/{date}/research_decision.json) 는 24-cell field 갖고
        # 있음. extra="ignore" 로 deserialize 시 무시 — 호환성 유지 (C7 에서 재생성 예정).
        "extra": "ignore",
    }


class InvestmentThesis(BaseModel):
    """Research Manager(Stage 2) 출력 — bull/bear 종합. structured LLM 타깃."""
    thesis_md: str = Field(max_length=20000)
    conviction: ConvictionLevel = "medium"
    dominant_scenario: ScenarioField = "neutral"
    key_risks: list[str] = Field(default_factory=list)


class ResearchThesis(BaseModel):
    """Stage 2 종합 state 객체 (state['research_decision']).

    factor model 제거 후 ResearchDecision 을 대체. Stage 4 macro_conditional 이
    getattr(rd, 'dominant_scenario'|'conviction') 로 읽으므로 동일 필드명 유지.
    factor_scores 는 없음 → macro_conditional 의 valuation trigger graceful 비활성.
    """
    conviction: ConvictionLevel = "medium"
    dominant_scenario: ScenarioField = "neutral"
    thesis_md: str = Field(default="", max_length=20000)
    bull_view: str = Field(default="", max_length=20000)
    bear_view: str = Field(default="", max_length=20000)
    key_risks: list[str] = Field(default_factory=list)
    model_config = {"extra": "ignore"}
