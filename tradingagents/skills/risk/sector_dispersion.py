"""Sector return dispersion — cross-sectional std of sector ETF 60d returns.

Narrow market (AI rally) → low dispersion. Broad market → high dispersion.
Factor model F9 liquidity_regime component (C8 활성화 예정).

C7 patterns (5 indicator pattern 의 마지막 *기존 schema 확장 indicator* 사례):
- D7 (기존 schema 확장): scalar return — analyst 가 BreadthSnapshot.model_copy
  로 sector_return_dispersion field 에 채움. C3/C4 와 동일 path.
- D8: empty / single sector / exception → None + logger.warning (no default fill).
- D9: no retry, no skill-internal cache (fetcher cache 와 분리).
"""
import logging

import numpy as np

from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(name="compute_sector_dispersion", category="risk")
def compute_sector_dispersion(sector_60d_returns: dict[str, float]) -> float | None:
    """Returns std of sector returns (decimal scale, e.g., 0.05 = 5pp).

    Args:
        sector_60d_returns: {sector_ticker: 60d_return_decimal}.
            Empty / 1 sector → None (insufficient data).

    Returns:
        Cross-sectional std (decimal), or None if < 2 sectors.
    """
    try:
        if not sector_60d_returns or len(sector_60d_returns) < 2:
            logger.warning(
                "Sector dispersion: insufficient sectors (%d) — F9 component skipped",
                len(sector_60d_returns) if sector_60d_returns else 0,
            )
            return None
        values = np.array(list(sector_60d_returns.values()))
        return float(np.std(values, ddof=1))
    except Exception as e:
        logger.warning("Sector dispersion compute failed: %s", e)
        return None
