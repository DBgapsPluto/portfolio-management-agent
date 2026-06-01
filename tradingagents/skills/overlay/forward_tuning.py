"""Tier 3 forward-tuning: BAND auto-adjustment based on credibility history."""
from __future__ import annotations

import logging
from typing import Final

import numpy as np

from tradingagents.schemas.llm_overlay import CredibilityState

logger = logging.getLogger(__name__)

LOW_CRED_THRESHOLD:  Final[float] = 0.40
HIGH_CRED_THRESHOLD: Final[float] = 0.60
BAND_MIN: Final[float] = 0.03
BAND_MAX: Final[float] = 0.07
MIN_HISTORY_REBALANCES: Final[int] = 6
BUCKETS_PER_REBALANCE: Final[int] = 8


def auto_tune_band(state: CredibilityState, current_band: float) -> float:
    """After 6+ rebalances, adjust BAND +/-0.01 based on average cred.

    avg cred < 0.40 -> tighten (LLM unreliable); > 0.60 -> loosen (reliable).
    Insufficient history (< 6 rebalances) -> unchanged.
    """
    if state.history_count < MIN_HISTORY_REBALANCES * BUCKETS_PER_REBALANCE:
        return current_band
    if not state.bucket_cred:
        return current_band
    avg_cred = float(np.mean(list(state.bucket_cred.values())))
    if avg_cred < LOW_CRED_THRESHOLD:
        new_band = round(max(BAND_MIN, current_band - 0.01), 10)
    elif avg_cred > HIGH_CRED_THRESHOLD:
        new_band = round(min(BAND_MAX, current_band + 0.01), 10)
    else:
        new_band = current_band
    if new_band != current_band:
        logger.info("Tier 3 BAND auto-tune: %.2f -> %.2f (avg_cred=%.2f)",
                    current_band, new_band, avg_cred)
    return new_band


__all__ = ["auto_tune_band", "BAND_MIN", "BAND_MAX"]
