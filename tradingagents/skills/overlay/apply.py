"""Tier 3 LLM overlay blending + mandate projection."""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from tradingagents.schemas.llm_overlay import LLMBucketView, CredibilityState
from tradingagents.skills.overlay.credibility import get_credibility
from tradingagents.skills.research.factor_to_bucket import BUCKETS, project_to_mandate_qp

logger = logging.getLogger(__name__)

BAND: Final[float] = 0.05  # +/-5pp per-bucket delta cap


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


__all__ = ["apply_llm_overlay", "BAND"]
