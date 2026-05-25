"""Concentration lens — HHI + top-N + cluster exposure.

LLM-free deterministic. Mandate (단일 cap 20% + cluster cap 0.25 hard)는
Stage 5 validator가 보유. Stage 4 lens는 *시장 위험 시 추가 strict한* cap만
제안 (책임 분리, Stage 5 정리 ⑥ 옵션 A-1).

Threshold:
  critical: HHI > CRITICAL_HHI=0.20 OR max_cluster > CRITICAL_CLUSTER=0.50 OR top1 > TOP1_CRITICAL=0.19
  high:     HHI > HIGH_HHI=0.15 OR max_cluster > HIGH_CLUSTER=0.40 OR top3 > TOP3_HIGH=0.50
  medium:   HHI > MEDIUM_HHI=0.12 OR max_cluster > MEDIUM_CLUSTER=0.30
  low:      HHI > LOW_HHI=0.10
  none:     else

Overlay cluster_caps (validator baseline 0.25 대비 strict-only):
  critical: cluster_caps = {top-1: CRITICAL_CLUSTER_CAP=0.18}     # -7%p
  high:     cluster_caps = {top-1: HIGH_CLUSTER_CAP=0.22}         # -3%p
  medium:   cluster_caps 비움 (validator baseline 0.25로 충분)
  low/none: empty

Weight ceilings (단일 자산 cap 0.20 대비 strict-only):
  critical: top-2 ticker → CRITICAL_WEIGHT_CEILING=0.15
  high:     top-1 ticker → HIGH_WEIGHT_CEILING=0.17
"""
import logging

from tradingagents.skills.risk.portfolio_metrics import PortfolioNumerics
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.schemas.risk_overlay import LensConcern, RiskOverlayDelta

logger = logging.getLogger(__name__)


# Stage 4 audit (2026-05-26, Task 2): named constants.
CRITICAL_HHI: float = 0.20
HIGH_HHI: float = 0.15
MEDIUM_HHI: float = 0.12
LOW_HHI: float = 0.10

CRITICAL_CLUSTER: float = 0.50
HIGH_CLUSTER: float = 0.40
MEDIUM_CLUSTER: float = 0.30

TOP1_CRITICAL: float = 0.19   # 단일 자산 19% 초과 — single cap 20% 직전
TOP3_HIGH: float = 0.50       # 상위 3개 자산 합 50% 초과

# Preset overlay levels (validator baseline 0.25 / 0.20 대비 strict-only).
CRITICAL_CLUSTER_CAP: float = 0.18   # -7%p
HIGH_CLUSTER_CAP: float = 0.22       # -3%p
CRITICAL_WEIGHT_CEILING: float = 0.15
HIGH_WEIGHT_CEILING: float = 0.17


def _level_from_inputs(
    hhi: float, max_cluster: float, top1: float, top3: float,
) -> str:
    if hhi > CRITICAL_HHI or max_cluster > CRITICAL_CLUSTER or top1 > TOP1_CRITICAL:
        return "critical"
    if hhi > HIGH_HHI or max_cluster > HIGH_CLUSTER or top3 > TOP3_HIGH:
        return "high"
    if hhi > MEDIUM_HHI or max_cluster > MEDIUM_CLUSTER:
        return "medium"
    if hhi > LOW_HHI:
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
        ceilings = {t: CRITICAL_WEIGHT_CEILING for t, _w in sorted_weights[:2]}
        caps = {c: CRITICAL_CLUSTER_CAP for c, _e in sorted_clusters[:1]}
        return RiskOverlayDelta(weight_ceilings=ceilings, cluster_caps=caps)
    if level == "high":
        ceilings = (
            {sorted_weights[0][0]: HIGH_WEIGHT_CEILING}
            if sorted_weights else {}
        )
        caps = {c: HIGH_CLUSTER_CAP for c, _e in sorted_clusters[:1]}
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
    logger.debug(
        "concentration_lens: HHI=%.3f, max_cluster=%.3f, top1=%.3f, top3=%.3f → %s",
        hhi, max_cluster, top1, top3, level,
    )

    evidence = (
        f"HHI={hhi:.3f}, top1={top1*100:.1f}%, top3_sum={top3*100:.1f}%, "
        f"max_cluster={max_cluster*100:.1f}% ({len(numerics.cluster_exposure)} clusters)"
    )[:300]

    return LensConcern(
        lens="concentration", level=level,  # type: ignore[arg-type]
        proposed_overlay=overlay, evidence=evidence,
    )
