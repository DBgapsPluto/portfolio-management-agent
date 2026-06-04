"""Tier 3 novelty + salience persistence.

Novelty = clip(z(today_salience) / 3.0, 0, 1)
Salience = log(1 + high_impact_count) + |macro_sentiment|
History: data/llm_overlay/salience_history.parquet (daily append-only).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SALIENCE_HISTORY_PATH: Final[Path] = Path("data/llm_overlay/salience_history.parquet")
MIN_HISTORY_POINTS: Final[int] = 10
BOOTSTRAP_SALIENCE_LEVELS: Final[tuple[float, ...]] = (
    0.35, 0.40, 0.45, 0.50, 0.55,
    0.35, 0.40, 0.45, 0.50, 0.55,
    0.35, 0.40, 0.45, 0.50, 0.55,
    0.35, 0.40, 0.45, 0.50, 0.55,
)


def _safe_get(obj, *path, default=None):
    cur = obj
    for k in path:
        if cur is None:
            return default
        try:
            cur = getattr(cur, k)
        except AttributeError:
            try:
                cur = cur[k]
            except Exception:
                return default
    return cur if cur is not None else default


def _compute_today_salience(news_report: Any) -> float:
    high_imp = float(_safe_get(news_report, "release_surprise", "high_importance_today", default=0) or 0)
    sent = _safe_get(news_report, "news_sentiment", "avg_sentiment", "macro", default=0.0)
    sent_mag = abs(float(sent or 0.0))
    return float(np.log1p(high_imp) + sent_mag)


def append_daily_salience(news_report: Any, run_date: date) -> None:
    """Idempotent daily append. Same date → no-op."""
    if news_report is None:
        return
    salience = _compute_today_salience(news_report)
    row = pd.DataFrame({"date": [run_date], "salience": [salience]})
    if SALIENCE_HISTORY_PATH.exists():
        existing = pd.read_parquet(SALIENCE_HISTORY_PATH)
        if run_date in existing["date"].values:
            return
        combined = pd.concat([existing, row], ignore_index=True).sort_values("date")
    else:
        SALIENCE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        combined = row
    combined.to_parquet(SALIENCE_HISTORY_PATH, index=False)


def load_salience_history(as_of: date, window_days: int = 60) -> pd.Series:
    if not SALIENCE_HISTORY_PATH.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(SALIENCE_HISTORY_PATH)
    cutoff = as_of - timedelta(days=window_days)
    df = df[(df["date"] >= cutoff) & (df["date"] < as_of)]
    return df.set_index("date")["salience"]


def _bootstrap_salience_history() -> pd.Series:
    return pd.Series(BOOTSTRAP_SALIENCE_LEVELS, dtype=float)


def compute_novelty(news_report: Any, as_of: date, window_days: int = 60) -> float:
    """News salience anomaly score, in [0, 1]."""
    if news_report is None:
        return 0.0
    today = _compute_today_salience(news_report)
    history = load_salience_history(as_of, window_days)
    if len(history) < MIN_HISTORY_POINTS:
        history = _bootstrap_salience_history()
    mu = float(history.mean())
    sd = float(history.std(ddof=1)) or 1e-9
    z = (today - mu) / sd
    return float(np.clip(z / 3.0, 0.0, 1.0))


__all__ = [
    "compute_novelty", "append_daily_salience", "load_salience_history",
    "SALIENCE_HISTORY_PATH", "MIN_HISTORY_POINTS", "BOOTSTRAP_SALIENCE_LEVELS",
]
