"""Skew metrics — 1-month change z-score for factor model F7.

CBOE SKEW index measures the perceived tail risk of S&P 500. Range typically 100-150.
*Level* 는 post-2018 structurally elevated (reliability medium-low) — 그래서 기존
SkewSnapshot.tail_hedge_signal 도 1y percentile 기반으로 reframe 됨.

*1m change z* (delta from 1 month ago, normalized) 가 *cleaner signal* for vol
regime detection — base shift 와 무관하게 momentum 잡힘.

C7.5 patterns (Grill-me #3 D11b — F7 skew_change placeholder 해소):
- D7 (기존 schema 확장): scalar return — analyst 가 SkewSnapshot.model_copy
  로 change_1m_z field 에 채움. C3/C4/C7 와 동일 path.
- D8: insufficient series (<21 obs) / exception → None + logger.warning.
- D9: no retry, no skill-internal cache.
"""
import logging
from datetime import date

import pandas as pd

from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)

# Long-run sd of 1-month SKEW change. Hand-coded approximation;
# empirical historical 1-month change std ≈ 5-7 (typical range observed in
# 2015-2025 SKEW data). 5.0 conservative — slightly inflates z magnitude
# (errs on side of detecting regime shift).
_SKEW_1M_CHANGE_SD: float = 5.0

# 21 trading days ≈ 1 month. iloc[-21] from a ≥21-obs series gives the 21st-to-last
# observation; for a series of N=22, this is the very first sample (latest - 21 positions).
_LOOKBACK_DAYS: int = 21


@register_skill(name="compute_skew_change_z", category="risk")
def compute_skew_change_z(
    skew_series: pd.Series, as_of: date,
) -> float | None:
    """Returns z-score of 1-month change in SKEW value.

    Args:
        skew_series: SKEW index daily series (≥21 trading days required for 1m change).
        as_of: report date (not used for computation; kept for API symmetry with
            other risk skills).

    Returns:
        Z-score of (latest - 21d_ago) / sd, or None on insufficient data.
    """
    try:
        if skew_series is None or skew_series.empty or len(skew_series) < _LOOKBACK_DAYS:
            n = len(skew_series) if skew_series is not None else 0
            logger.warning(
                "SKEW change z: insufficient series (%d obs, need ≥%d) — "
                "F7 skew_change skipped",
                n, _LOOKBACK_DAYS,
            )
            return None
        latest = float(skew_series.iloc[-1])
        one_month_ago = float(skew_series.iloc[-_LOOKBACK_DAYS])
        change = latest - one_month_ago
        z = change / _SKEW_1M_CHANGE_SD
        return z
    except Exception as e:
        logger.warning("SKEW change z compute failed: %s", e)
        return None
