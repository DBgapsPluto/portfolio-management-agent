"""Tier 3 consensus = |sum(sign(delta))| / K per bucket."""
from __future__ import annotations
from typing import Final

import numpy as np

from tradingagents.schemas.llm_overlay import LLMBucketView
from tradingagents.skills.research.factor_to_bucket import BUCKETS

NEUTRAL_THRESHOLD: Final[float] = 0.1


def compute_consensus(views: list[LLMBucketView]) -> dict[str, float]:
    """Per-bucket consensus in [0, 1]. K-sample sign agreement."""
    result: dict[str, float] = {}
    if not views:
        return {b: 0.0 for b in BUCKETS}
    for bucket in BUCKETS:
        signs = []
        for v in views:
            delta = getattr(v, bucket)
            s = np.sign(delta) if abs(delta) >= NEUTRAL_THRESHOLD else 0
            signs.append(s)
        if all(s == 0 for s in signs):
            result[bucket] = 0.0
        else:
            result[bucket] = abs(sum(signs)) / len(signs)
    return result


__all__ = ["compute_consensus", "NEUTRAL_THRESHOLD"]
