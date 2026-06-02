"""Stage 4 RiskOverlay — LLM이 weight를 직접 산출하지 않고 *제약*만 산출.

기존 WeightAdjustment.delta (LLM이 ticker별 delta 산출)는 Stage 2 Bull/Bear와
같은 advocacy 결함 + mandate-safe weight를 후처리로 깨뜨릴 위험으로 폐기.

대체: RiskOverlay는 ceilings/floors/cluster_caps/multiplier 형태로 *제약*을
산출하고 optimizer가 mandate-safe하게 풀어준다. Stage 3 method_picker가
method 선택 → optimizer 풀이 패턴의 확장.
"""
from typing import Literal

from pydantic import BaseModel, Field

from tradingagents.schemas._base import StalenessAware


LensName = Literal["tail_risk", "concentration", "macro_conditional"]
ConcernLevel = Literal["none", "low", "medium", "high", "critical"]
OverlayOutcome = Literal[
    "primary_success", "relax_cluster", "relax_ceiling",
    "relax_band", "fallback_to_1st", "weights_shrunk",
]


class RiskOverlayDelta(BaseModel):
    """단일 lens가 제안하는 overlay 부분 — Judge가 severity-gated 머지.

    모든 필드 optional, 빈 dict / 1.0 multiplier는 no-op.
    """
    weight_ceilings: dict[str, float] = Field(
        default_factory=dict,
        description="ticker → max weight (단일 자산 cap을 더 좁힐 때). "
                    "Stage 3 단일 cap 20%와 결합되어 더 엄격한 값이 적용됨.",
    )
    cluster_caps: dict[str, float] = Field(
        default_factory=dict,
        description="cluster_id → 클러스터 합 max. Stage 1 correlation_clusters 참조.",
    )
    risk_asset_multiplier: float = Field(
        default=1.0, ge=0.5, le=1.0,
        description="위험자산 (kr/global eq + fx_comm) bucket weight 배율. "
                    "< 1.0이면 defensive shift, 줄어든 만큼 bond+mmf로 재정규화.",
    )
    tail_hedge_floor: dict[str, float] = Field(
        default_factory=dict,
        description="ticker → min weight (tail hedge 강제 floor). "
                    "단일 cap 20%과 충돌 시 floor 우선, infeasible 시 overlay fallback.",
    )

    def is_empty(self) -> bool:
        return (
            not self.weight_ceilings
            and not self.cluster_caps
            and self.risk_asset_multiplier >= 0.999
            and not self.tail_hedge_floor
        )


class LensConcern(BaseModel):
    """단일 lens 출력 — Phase 2.

    Aggressive/Conservative/Neutral의 advocacy 폐기 → lens 별로 *정량 측정*된
    risk concern 산출. evidence 필드에 구체 수치 인용 강제.
    """
    lens: LensName
    level: ConcernLevel
    proposed_overlay: RiskOverlayDelta = Field(default_factory=RiskOverlayDelta)
    evidence: str = Field(
        max_length=300,
        description="정량 수치 인용 강제. 예: 'HHI 0.18 > 0.15 threshold'",
    )


class RiskOverlay(StalenessAware):
    """Judge가 severity-gated 합의 후 산출하는 최종 overlay.

    Stage 3 2차 호출 시 weight_bounds/sector_constraints/bucket scaling으로
    변환되어 optimizer에 주입.
    """
    weight_ceilings: dict[str, float] = Field(default_factory=dict)
    cluster_caps: dict[str, float] = Field(default_factory=dict)
    risk_asset_multiplier: float = Field(default=1.0, ge=0.5, le=1.0)
    tail_hedge_floor: dict[str, float] = Field(default_factory=dict)

    # Provenance
    severity_decision: str = Field(
        default="no concerns",
        max_length=200,
        description="severity gate 결정 — 'critical 2명 → 100%' 같은 룰 인용",
    )
    strength_applied: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="severity_decision으로 결정된 강도. 0이면 lens delta 무시.",
    )
    lens_concerns: list[LensConcern] = Field(
        default_factory=list, description="각 lens의 raw 출력 (archive용)",
    )
    overlay_apply_outcome: OverlayOutcome = Field(
        default="primary_success",
        description="apply_risk_overlay 가 어느 drop_level 에서 풀이를 성공했는지. "
                    "telemetry/감사용. is_empty() 인 경우도 'primary_success'.",
    )

    def is_empty(self) -> bool:
        return (
            not self.weight_ceilings
            and not self.cluster_caps
            and self.risk_asset_multiplier >= 0.999
            and not self.tail_hedge_floor
        )

    @classmethod
    def no_concerns(cls, as_of_date=None) -> "RiskOverlay":
        return cls(
            severity_decision="no concerns triggered",
            strength_applied=0.0,
            source_date=as_of_date,
        )
