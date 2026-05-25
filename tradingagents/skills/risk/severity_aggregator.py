"""Severity-gated aggregation — 3 LensConcern → 단일 RiskOverlay.

보수적 초기값 (Phase 2 → Phase 3에서 backtest calibration):
  critical ≥2  → STRENGTH_CRITICAL_TWO_PLUS=1.0 (full)
  critical 1   → STRENGTH_CRITICAL_ONE=0.7
  high     ≥2 → STRENGTH_HIGH_TWO_PLUS=0.5
  high     1   → STRENGTH_HIGH_ONE=0.3
  medium   ≥2 → STRENGTH_MEDIUM_TWO_PLUS=0.2
  else         → STRENGTH_NONE=0.0 (archive only)

각 lens의 proposed_overlay는 strength로 곱해져 머지:
  - weight_ceilings: lens별 min (가장 엄격) × strength 적용
  - cluster_caps: 동상
  - risk_asset_multiplier: 최저값 사용 (가장 defensive)
  - tail_hedge_floor: lens별 max (가장 강력)
"""
import logging
from collections import Counter

from tradingagents.schemas.risk_overlay import (
    LensConcern, RiskOverlay, RiskOverlayDelta,
)
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


# Stage 4 audit (2026-05-26, Task 3): strength gates named.
STRENGTH_CRITICAL_TWO_PLUS: float = 1.0   # 2개 이상 lens 가 critical → full overlay
STRENGTH_CRITICAL_ONE: float = 0.7        # 1개 critical (conservative)
STRENGTH_HIGH_TWO_PLUS: float = 0.5       # 2개 이상 high (consensus)
STRENGTH_HIGH_ONE: float = 0.3
STRENGTH_MEDIUM_TWO_PLUS: float = 0.2
STRENGTH_NONE: float = 0.0

# Merge logic bounds.
WEIGHT_CEILING_MAX: float = 0.20    # single asset cap (mandate); relaxed cap upper
CLUSTER_CAP_MAX: float = 1.0
MULTIPLIER_FLOOR: float = 0.5       # multiplier 최저 (50% 위험자산 cap)
FLOOR_MAX: float = 0.20             # tail_hedge_floor 최대


def _decide_strength(concerns: list[LensConcern]) -> tuple[float, str]:
    levels = Counter(c.level for c in concerns)
    n_crit = levels.get("critical", 0)
    n_high = levels.get("high", 0)
    n_med = levels.get("medium", 0)

    if n_crit >= 2:
        return STRENGTH_CRITICAL_TWO_PLUS, f"critical ≥2 (n={n_crit}) → full strength"
    if n_crit >= 1:
        return STRENGTH_CRITICAL_ONE, "critical 1 → 70% strength (conservative initial)"
    if n_high >= 2:
        return STRENGTH_HIGH_TWO_PLUS, f"high ≥2 consensus (n={n_high}) → 50% strength"
    if n_high >= 1:
        return STRENGTH_HIGH_ONE, "high 1 → 30% strength"
    if n_med >= 2:
        return STRENGTH_MEDIUM_TWO_PLUS, f"medium ≥2 (n={n_med}) → 20% strength"
    return STRENGTH_NONE, "low/single medium/none → archive only"


def _merge_deltas(
    concerns: list[LensConcern], strength: float,
) -> RiskOverlayDelta:
    """strength로 lens deltas 머지. strength=0이면 empty."""
    if strength <= 0:
        return RiskOverlayDelta()

    # weight_ceilings: 가장 엄격 (min)
    ceilings: dict[str, float] = {}
    # cluster_caps: 가장 엄격 (min)
    caps: dict[str, float] = {}
    # risk_asset_multiplier: 가장 defensive (min)
    multipliers: list[float] = []
    # tail_hedge_floor: 가장 강력 (max)
    floors: dict[str, float] = {}

    for c in concerns:
        d = c.proposed_overlay

        for ticker, ceil in d.weight_ceilings.items():
            # strength 적용: ceiling을 strength로 보간 (1.0이면 그대로, 0.5면 절반 강도)
            relaxed = ceil + (WEIGHT_CEILING_MAX - ceil) * (1.0 - strength)
            relaxed = min(WEIGHT_CEILING_MAX, max(0.0, relaxed))
            if ticker not in ceilings or relaxed < ceilings[ticker]:
                ceilings[ticker] = relaxed

        for cid, cap in d.cluster_caps.items():
            relaxed = cap + (CLUSTER_CAP_MAX - cap) * (1.0 - strength)
            relaxed = min(CLUSTER_CAP_MAX, max(0.0, relaxed))
            if cid not in caps or relaxed < caps[cid]:
                caps[cid] = relaxed

        # multiplier: 1.0에서 d.multiplier로 향하는 strength 비율
        if d.risk_asset_multiplier < 1.0:
            blended = 1.0 - (1.0 - d.risk_asset_multiplier) * strength
            blended = max(MULTIPLIER_FLOOR, min(1.0, blended))
            multipliers.append(blended)

        for ticker, floor in d.tail_hedge_floor.items():
            scaled = floor * strength
            scaled = max(0.0, min(FLOOR_MAX, scaled))
            if ticker not in floors or scaled > floors[ticker]:
                floors[ticker] = scaled

    final_multiplier = min(multipliers) if multipliers else 1.0

    return RiskOverlayDelta(
        weight_ceilings=ceilings,
        cluster_caps=caps,
        risk_asset_multiplier=final_multiplier,
        tail_hedge_floor=floors,
    )


@register_skill(name="aggregate_lens_concerns", category="risk")
def aggregate_lens_concerns(
    concerns: list[LensConcern], as_of_date=None,
) -> RiskOverlay:
    """Severity-gated 합의 → 단일 RiskOverlay.

    빈 input이거나 모든 lens level=none/low → RiskOverlay.no_concerns().
    """
    if not concerns:
        return RiskOverlay.no_concerns(as_of_date=as_of_date)

    strength, decision = _decide_strength(concerns)
    logger.info(
        "severity_aggregator: %d concerns (%s) → strength=%.2f (%s)",
        len(concerns),
        ", ".join(f"{c.lens}={c.level}" for c in concerns),
        strength, decision,
    )

    if strength <= 0:
        return RiskOverlay(
            severity_decision=decision,
            strength_applied=0.0,
            lens_concerns=concerns,
            source_date=as_of_date,
        )

    merged = _merge_deltas(concerns, strength)

    return RiskOverlay(
        weight_ceilings=merged.weight_ceilings,
        cluster_caps=merged.cluster_caps,
        risk_asset_multiplier=merged.risk_asset_multiplier,
        tail_hedge_floor=merged.tail_hedge_floor,
        severity_decision=decision,
        strength_applied=strength,
        lens_concerns=concerns,
        source_date=as_of_date,
    )
