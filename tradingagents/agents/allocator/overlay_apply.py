"""Stage 4 RiskOverlay 를 Stage 3 weight_vector 에 직접 적용(재최적화 없음).

흐름:
  Stage 3 → WeightVector w1
  Stage 4 → RiskOverlay
  apply_overlay_to_weights (이 모듈):
    overlay 비면 → (w1, False)
    overlay 차면 → 비중 shrink/clip, 남은 비중에 재분배 → (w2, True)

적용 순서:
  1) risk_asset_multiplier < 1 → 위험 종목 비례 축소, 축소분을 안전 종목에 비례 재분배.
  2) weight_ceilings → 해당 종목 clip, 초과분 나머지에 비례 재분배.
  전부 끝나면 sum=1 로 renormalize.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def apply_overlay_to_weights(
    weight_vector: "WeightVector",
    overlay: "RiskOverlay",
    risk_flags: dict[str, str],
) -> tuple["WeightVector", bool]:
    """RiskOverlay 를 weight_vector 에 직접 적용(재최적화 없음, 비중 구조 보존).

    1) risk_asset_multiplier < 1 → 위험 종목 비례 축소, 축소분을 안전 종목에 비례 재분배.
    2) weight_ceilings → 해당 종목 clip, 초과분 나머지에 비례 재분배.
    전부 끝나면 sum=1 로 renormalize.
    """
    w = dict(weight_vector.weights)
    changed = False
    m = getattr(overlay, "risk_asset_multiplier", 1.0) or 1.0

    if m < 1.0 - 1e-9:
        risk_t = [t for t in w if risk_flags.get(t) == "위험"]
        safe_t = [t for t in w if risk_flags.get(t) != "위험"]
        freed = 0.0
        for t in risk_t:
            new = w[t] * m
            freed += w[t] - new
            w[t] = new
        safe_sum = sum(w[t] for t in safe_t)
        if safe_sum > 1e-9 and freed > 0:
            for t in safe_t:
                w[t] += freed * w[t] / safe_sum
        changed = True

    ceilings = getattr(overlay, "weight_ceilings", {}) or {}
    for t, cap in ceilings.items():
        if t in w and w[t] > cap + 1e-9:
            excess = w[t] - cap
            w[t] = cap
            others = [o for o in w if o != t]
            osum = sum(w[o] for o in others)
            if osum > 1e-9:
                for o in others:
                    w[o] += excess * w[o] / osum
            changed = True

    s = sum(w.values())
    if s > 1e-9:
        w = {t: v / s for t, v in w.items()}

    if not changed:
        return weight_vector, False
    return weight_vector.model_copy(update={"weights": w}), True
