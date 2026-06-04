"""Tier 3 LLM overlay blending + mandate projection."""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from tradingagents.schemas.llm_overlay import (
    LLMBucketView, Stage2NarrativeView, CredibilityState,
)
from tradingagents.skills.overlay.credibility import get_credibility
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, RISK_BUCKETS, project_to_mandate_qp,
)

logger = logging.getLogger(__name__)

BAND: Final[float] = 0.05  # +/-5pp per-bucket delta cap
STAGE2_NARRATIVE_BAND: Final[float] = 0.03
STAGE2_RISK_BUDGET_BAND: Final[float] = 0.05
CONFLICT_GATE_MULTIPLIER: Final[float] = 0.5


def _aggregate_views(views: list[LLMBucketView]) -> dict[str, float]:
    """Per-bucket mean delta x average confidence."""
    if not views:
        return {b: 0.0 for b in BUCKETS}
    avg_conf = float(np.mean([v.confidence for v in views]))
    result = {}
    for bucket in BUCKETS:
        deltas = [getattr(v, bucket) for v in views]
        result[bucket] = float(np.mean(deltas)) * avg_conf
    return result


def apply_llm_overlay(
    quant_target: dict[str, float],
    views: list[LLMBucketView],
    novelty: float,
    consensus: dict[str, float],
    credibility: CredibilityState,
    band: float = BAND,
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Blend quant + LLM directional view -> mandate-compliant target.

    w_LLM(b) = novelty x consensus[b] x credibility[b]
    delta(b) = clip(w_LLM x avg_delta(b), -band, +band)   [avg_delta already x avg_confidence]
    blended(b) = quant_target[b] + delta(b)
    final = project_to_mandate_qp(blended)   # enforces sum=1 + risk<=0.70
    """
    avg_delta = _aggregate_views(views)
    audit: dict[str, dict[str, float]] = {}
    blended = dict(quant_target)
    for bucket in BUCKETS:
        w = novelty * consensus.get(bucket, 0.0) * get_credibility(credibility, bucket)
        raw_delta = w * avg_delta.get(bucket, 0.0)
        clipped = float(np.clip(raw_delta, -band, band))
        blended[bucket] = quant_target.get(bucket, 0.0) + clipped
        audit[bucket] = {
            "quant":         quant_target.get(bucket, 0.0),
            "llm_avg_delta": avg_delta.get(bucket, 0.0),
            "w_LLM":         w,
            "clipped_delta": clipped,
            "blended":       blended[bucket],
        }
    final = project_to_mandate_qp(blended)
    return final, audit


def _aggregate_narrative_views(
    views: list[Stage2NarrativeView],
) -> tuple[dict[str, float], float, float, float]:
    """Aggregate Stage 2 narrative views.

    Returns:
        bucket_delta: per-bucket mean directional delta x average confidence
        risk_delta: mean risk-budget direction x average confidence
        avg_conf: average LLM self-confidence
        conflict_rate: share of samples that declare conflict with quant
    """
    if not views:
        return {b: 0.0 for b in BUCKETS}, 0.0, 0.0, 0.0
    avg_conf = float(np.mean([v.confidence for v in views]))
    conflict_rate = float(np.mean([1.0 if v.conflict_with_quant else 0.0 for v in views]))
    bucket_delta = {}
    for bucket in BUCKETS:
        deltas = [v.bucket_deltas.get(bucket, 0.0) for v in views]
        bucket_delta[bucket] = float(np.mean(deltas)) * avg_conf
    risk_delta = float(np.mean([v.risk_budget_delta for v in views])) * avg_conf
    return bucket_delta, risk_delta, avg_conf, conflict_rate


def _apply_risk_budget_shift(
    bucket_target: dict[str, float],
    risk_shift: float,
) -> dict[str, float]:
    """Shift total risk-asset weight while preserving relative risk/safe mix."""
    if abs(risk_shift) < 1e-12:
        return dict(bucket_target)
    out = dict(bucket_target)
    risk_total = sum(out.get(b, 0.0) for b in RISK_BUCKETS)
    safe_keys = [b for b in out if b not in RISK_BUCKETS]
    safe_total = sum(out.get(b, 0.0) for b in safe_keys)
    if risk_total <= 0 or safe_total <= 0:
        return out
    new_risk = min(0.70, max(0.0, risk_total + risk_shift))
    realized_shift = new_risk - risk_total
    risk_scale = new_risk / risk_total
    for bucket in RISK_BUCKETS:
        out[bucket] = out.get(bucket, 0.0) * risk_scale
    for bucket in safe_keys:
        share = out.get(bucket, 0.0) / safe_total
        out[bucket] = out.get(bucket, 0.0) - realized_shift * share
    return out


def apply_stage2_narrative_overlay(
    quant_target: dict[str, float],
    views: list[Stage2NarrativeView],
    novelty: float,
    consensus: dict[str, float],
    credibility: CredibilityState,
    band: float = STAGE2_NARRATIVE_BAND,
    llm_max_mix: float = 0.20,
    risk_budget_band: float = STAGE2_RISK_BUDGET_BAND,
) -> tuple[dict[str, float], dict[str, dict[str, float] | float]]:
    """Blend quant bucket target with bounded Stage 2 LLM narrative views.

    The LLM supplies direction only. Numeric impact is bounded by gates
    (novelty, consensus, credibility, conflict) and projected back to mandate.
    """
    avg_delta, risk_delta, avg_conf, conflict_rate = _aggregate_narrative_views(views)
    conflict_gate = 1.0 - (CONFLICT_GATE_MULTIPLIER * conflict_rate)
    conflict_gate = max(0.0, min(1.0, conflict_gate))
    base_mix = max(0.0, min(1.0, llm_max_mix)) * max(0.0, min(1.0, novelty))
    blended = dict(quant_target)
    audit: dict[str, dict[str, float] | float] = {
        "avg_confidence": avg_conf,
        "conflict_rate": conflict_rate,
        "conflict_gate": conflict_gate,
        "base_mix": base_mix,
    }

    for bucket in BUCKETS:
        w = (
            base_mix
            * consensus.get(bucket, 0.0)
            * get_credibility(credibility, bucket)
            * conflict_gate
        )
        raw_delta = w * avg_delta.get(bucket, 0.0)
        clipped = float(np.clip(raw_delta, -band, band))
        blended[bucket] = quant_target.get(bucket, 0.0) + clipped
        audit[bucket] = {
            "quant": quant_target.get(bucket, 0.0),
            "llm_avg_delta": avg_delta.get(bucket, 0.0),
            "w_LLM": w,
            "raw_delta": raw_delta,
            "clipped_delta": clipped,
            "blended": blended[bucket],
        }

    mean_cred = float(np.mean([get_credibility(credibility, b) for b in BUCKETS]))
    risk_effective_weight = base_mix * mean_cred * conflict_gate
    risk_shift = float(np.clip(
        risk_effective_weight * risk_delta,
        -risk_budget_band,
        risk_budget_band,
    ))
    audit["risk_budget"] = {
        "llm_avg_delta": risk_delta,
        "w_LLM": risk_effective_weight,
        "clipped_delta": risk_shift,
    }
    blended = _apply_risk_budget_shift(blended, risk_shift)

    final = project_to_mandate_qp(blended)
    return final, audit


__all__ = [
    "apply_llm_overlay", "apply_stage2_narrative_overlay",
    "BAND", "STAGE2_NARRATIVE_BAND", "STAGE2_RISK_BUDGET_BAND",
]
