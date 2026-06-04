"""Tier 3 credibility EWMA + JSON persistence.

Cold start cred=0.3. EWMA: cred_new = (1-a)*cred_old + a*hit, a=0.1.
Hit: sign(predicted_delta) * sign(realized_return) > 0.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Final

from tradingagents.schemas.llm_overlay import CredibilityState
from tradingagents.skills.research.factor_to_bucket import BUCKETS

logger = logging.getLogger(__name__)

CRED_PATH: Final[Path] = Path("data/llm_overlay/credibility.json")
COLD_START_PRIOR: Final[float] = 0.3
BOOTSTRAP_CREDIBILITY_PRIOR: Final[float] = 0.45
BOOTSTRAP_HISTORY_COUNT: Final[int] = 8
EWMA_ALPHA: Final[float] = 0.1
MIN_SIGNAL_THRESHOLD: Final[float] = 0.005


def get_credibility(state: CredibilityState, bucket: str) -> float:
    return state.bucket_cred.get(bucket, COLD_START_PRIOR)


def update_credibility(state: CredibilityState, bucket: str,
                       predicted_delta: float, realized_return: float) -> None:
    """EWMA update. Persists state after each update. Skips sub-threshold signals."""
    if abs(predicted_delta) < MIN_SIGNAL_THRESHOLD or abs(realized_return) < MIN_SIGNAL_THRESHOLD:
        return
    hit = 1.0 if predicted_delta * realized_return > 0 else 0.0
    current = get_credibility(state, bucket)
    state.bucket_cred[bucket] = (1 - EWMA_ALPHA) * current + EWMA_ALPHA * hit
    state.history_count += 1
    state.last_updated = date.today()
    save_credibility(state)


def load_credibility() -> CredibilityState:
    if not CRED_PATH.exists():
        return CredibilityState(
            bucket_cred={b: BOOTSTRAP_CREDIBILITY_PRIOR for b in BUCKETS},
            history_count=BOOTSTRAP_HISTORY_COUNT,
            last_updated=date.today(),
        )
    data = json.loads(CRED_PATH.read_text())
    return CredibilityState(
        bucket_cred=data.get("bucket_cred", {}),
        history_count=data.get("history_count", 0),
        last_updated=date.fromisoformat(data.get("last_updated", date.today().isoformat())),
    )


def save_credibility(state: CredibilityState) -> None:
    CRED_PATH.parent.mkdir(parents=True, exist_ok=True)
    CRED_PATH.write_text(json.dumps({
        "bucket_cred": state.bucket_cred,
        "history_count": state.history_count,
        "last_updated": state.last_updated.isoformat(),
    }, indent=2))


__all__ = [
    "get_credibility", "update_credibility", "load_credibility", "save_credibility",
    "COLD_START_PRIOR", "BOOTSTRAP_CREDIBILITY_PRIOR", "BOOTSTRAP_HISTORY_COUNT",
    "EWMA_ALPHA", "CRED_PATH",
]
