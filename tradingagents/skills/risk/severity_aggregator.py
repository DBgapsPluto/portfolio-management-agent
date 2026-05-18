"""Severity-gated aggregation — 3 LensConcern → 단일 RiskOverlay.

보수적 초기값 (Phase 2 → Phase 3에서 backtest calibration):
  critical ≥2  → 1.0 strength (full)
  critical 1   → 0.7
  high     ≥2 → 0.5
  high     1   → 0.3
  medium   ≥2 → 0.2
  else         → empty (archive only)

각 lens의 proposed_overlay는 strength로 곱해져 머지:
  - weight_ceilings: lens별 min (가장 엄격) × strength 적용
  - cluster_caps: 동상
  - risk_asset_multiplier: 최저값 사용 (가장 defensive)
  - tail_hedge_floor: lens별 max (가장 강력)
"""
from collections import Counter

from tradingagents.schemas.risk_overlay import (
    LensConcern, RiskOverlay, RiskOverlayDelta,
)
from tradingagents.skills.registry import register_skill


_SEVERITY_GATE = {
    # (n_critical, n_high, n_medium) → strength
    # 우선순위로 평가 (위에서 아래로)
}


def _decide_strength(concerns: list[LensConcern]) -> tuple[float, str]:
    levels = Counter(c.level for c in concerns)
    n_crit = levels.get("critical", 0)
    n_high = levels.get("high", 0)
    n_med = levels.get("medium", 0)

    if n_crit >= 2:
        return 1.0, f"critical ≥2 (n={n_crit}) → full strength"
    if n_crit >= 1:
        return 0.7, f"critical 1 → 70% strength (conservative initial)"
    if n_high >= 2:
        return 0.5, f"high ≥2 consensus (n={n_high}) → 50% strength"
    if n_high >= 1:
        return 0.3, f"high 1 → 30% strength"
    if n_med >= 2:
        return 0.2, f"medium ≥2 (n={n_med}) → 20% strength"
    return 0.0, "low/single medium/none → archive only"


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
            relaxed = ceil + (0.20 - ceil) * (1.0 - strength)
            relaxed = min(0.20, max(0.0, relaxed))
            if ticker not in ceilings or relaxed < ceilings[ticker]:
                ceilings[ticker] = relaxed

        for cid, cap in d.cluster_caps.items():
            relaxed = cap + (1.0 - cap) * (1.0 - strength)
            relaxed = min(1.0, max(0.0, relaxed))
            if cid not in caps or relaxed < caps[cid]:
                caps[cid] = relaxed

        # multiplier: 1.0에서 d.multiplier로 향하는 strength 비율
        if d.risk_asset_multiplier < 1.0:
            blended = 1.0 - (1.0 - d.risk_asset_multiplier) * strength
            blended = max(0.5, min(1.0, blended))
            multipliers.append(blended)

        for ticker, floor in d.tail_hedge_floor.items():
            scaled = floor * strength
            scaled = max(0.0, min(0.20, scaled))
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
