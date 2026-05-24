"""CFNAI (Chicago Fed National Activity Index) — 85 real economy series composite.

CFNAI: 0 = trend growth (NBER baseline). +1 = well above trend, -1 = well below.
3-month MA (CFNAI-MA3) 가 standard recession signal (NBER convention).

Factor model F1 growth_surprise component (C8 활성화 예정).

C3 patterns (5 indicator pattern 의 첫 사례):
- D7: scalar tuple return (analyst applies fci.model_copy(update=...))
- D8: empty / exception → None (logger.warning, no default fill, no raise)
- D9: no retry / no cache inside skill (caller fetches fresh)
"""
import logging
from datetime import date

import pandas as pd

from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(name="compute_cfnai_metrics", category="macro")
def compute_cfnai_metrics(
    cfnai_series: pd.Series | None, as_of: date,
) -> tuple[float, float] | None:
    """Returns (cfnai_latest, cfnai_3m_avg). None if empty / unavailable.

    Args:
        cfnai_series: FRED CFNAI (monthly). None or empty → caller-side skip signal.
        as_of: report as-of date (advisory — series itself is point-in-time).

    Returns:
        (latest, 3m_avg) on success.
        None on data absence or exception (D8 graceful).

    Notes:
        - 1-2 obs → best-effort (avg = mean of available; latest = .iloc[-1]).
        - 3+ obs → standard CFNAI-MA3.
        - Analyst then applies fci.model_copy(update={"cfnai": ..., "cfnai_3m_avg": ...}).
    """
    try:
        if cfnai_series is None or len(cfnai_series) == 0:
            logger.warning(
                "CFNAI series unavailable (as_of=%s) — F1 growth_surprise component skipped",
                as_of,
            )
            return None
        cfnai_latest = float(cfnai_series.iloc[-1])
        # Best-effort: tail(3).mean() handles 1/2/3+ obs uniformly (pandas semantics).
        cfnai_3m_avg = float(cfnai_series.tail(3).mean())
        return cfnai_latest, cfnai_3m_avg
    except Exception as e:
        logger.warning("CFNAI metrics computation failed (as_of=%s): %s", as_of, e)
        return None
