"""Concentration lens — HHI + top-N + cluster exposure.

LLM-free deterministic. Mandate (단일 cap 20% + cluster cap 0.25 hard)는
Stage 5 validator가 보유. Stage 4 lens는 *시장 위험 시 추가 strict한* cap만
제안 (책임 분리, Stage 5 정리 ⑥ 옵션 A-1).

Threshold:
  critical: HHI > 0.20 OR max_cluster > 0.50 OR top1 > 0.19
  high:     HHI > 0.15 OR max_cluster > 0.40 OR top3 > 0.50
  medium:   HHI > 0.12 OR max_cluster > 0.30
  low:      HHI > 0.10
  none:     else

Overlay cluster_caps (validator baseline 0.25 대비 strict-only):
  critical: cluster_caps = {top-1: 0.18}     # baseline보다 -7%p strict
  high:     cluster_caps = {top-1: 0.22}     # -3%p
  medium:   cluster_caps 비움 (validator baseline 0.25로 충분)
  low/none: empty

Weight ceilings (단일 자산 cap 0.20 대비 strict-only):
  critical: weight_ceilings = top-2 ticker를 0.15로
  high:     top-1 ticker를 0.17
  medium:   empty (단일 cap만으로 충분)
"""
from tradingagents.skills.risk.portfolio_metrics import PortfolioNumerics
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.schemas.risk_overlay import LensConcern, RiskOverlayDelta


_CRITICAL_HHI = 0.20
_HIGH_HHI = 0.15
_MEDIUM_HHI = 0.12
_LOW_HHI = 0.10

_CRITICAL_CLUSTER = 0.50
_HIGH_CLUSTER = 0.40
_MEDIUM_CLUSTER = 0.30


def _level_from_inputs(
    hhi: float, max_cluster: float, top1: float, top3: float,
) -> str:
    if hhi > _CRITICAL_HHI or max_cluster > _CRITICAL_CLUSTER or top1 > 0.19:
        return "critical"
    if hhi > _HIGH_HHI or max_cluster > _HIGH_CLUSTER or top3 > 0.50:
        return "high"
    if hhi > _MEDIUM_HHI or max_cluster > _MEDIUM_CLUSTER:
        return "medium"
    if hhi > _LOW_HHI:
        return "low"
    return "none"


def _overlay_for_level(
    level: str, weight_vector: WeightVector,
    cluster_exposure: dict[str, float],
) -> RiskOverlayDelta:
    """level별 preset overlay.

    validator baseline (cluster_cap=0.25 hard, single cap=0.20 hard) 대비
    *strict-only* cap만 제안. validator보다 느슨한 cap은 no-op (제거).
    """
    sorted_weights = sorted(
        weight_vector.weights.items(), key=lambda kv: -kv[1],
    )
    sorted_clusters = sorted(
        cluster_exposure.items(), key=lambda kv: -kv[1],
    )

    if level == "critical":
        ceilings = {t: 0.15 for t, _w in sorted_weights[:2]}
        caps = {c: 0.18 for c, _e in sorted_clusters[:1]}
        return RiskOverlayDelta(weight_ceilings=ceilings, cluster_caps=caps)
    if level == "high":
        ceilings = {sorted_weights[0][0]: 0.17} if sorted_weights else {}
        caps = {c: 0.22 for c, _e in sorted_clusters[:1]}
        return RiskOverlayDelta(weight_ceilings=ceilings, cluster_caps=caps)
    # medium / low / none: validator baseline 0.25 cluster cap + 0.20 single cap
    # 으로 충분. Stage 4는 no-op.
    return RiskOverlayDelta()


def run_concentration_lens(
    numerics: PortfolioNumerics, weight_vector: WeightVector,
) -> LensConcern:
    """Concentration lens — HHI/cluster/top-N 기반."""
    hhi = numerics.hhi
    max_cluster = numerics.max_cluster_exposure
    top1 = numerics.top1_weight
    top3 = numerics.top3_weight_sum

    level = _level_from_inputs(hhi, max_cluster, top1, top3)
    overlay = _overlay_for_level(level, weight_vector, numerics.cluster_exposure)

    evidence = (
        f"HHI={hhi:.3f}, top1={top1*100:.1f}%, top3_sum={top3*100:.1f}%, "
        f"max_cluster={max_cluster*100:.1f}% ({len(numerics.cluster_exposure)} clusters)"
    )[:300]

    return LensConcern(
        lens="concentration", level=level,  # type: ignore[arg-type]
        proposed_overlay=overlay, evidence=evidence,
    )
