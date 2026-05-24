"""Realized volatility — SPY daily returns aggregated to 60d / 20d stddev.

VRP (variance risk premium): (VIX/100)² - realized² in bps²-like normalization.
Factor model F7 vol regime + F9 liquidity (via VRP) components (C8 활성화 예정).

C6 patterns (5 indicator pattern 의 두 번째 *신규 class indicator* 사례):
- D7 (신규 class): full Snapshot 반환 — analyst 가 RiskReport 의 Optional
  field 에 직접 채움 (model_copy 아님). C5 의 KRValuationSnapshot 와 동일 path.
- D8: empty / short / exception → None + logger.warning (no default fill, no raise)
- D9: no retry, no skill-internal cache (fetcher cache 와 분리)
"""
import logging
from datetime import date

import numpy as np
import pandas as pd

from tradingagents.schemas.risk import RealVolSnapshot
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(name="compute_realized_volatility", category="risk")
def compute_realized_volatility(
    daily_returns: pd.Series,
    vix_level: float | None,
    as_of: date,
) -> RealVolSnapshot | None:
    """Returns RealVolSnapshot with realized_vol_60d, realized_vol_20d, vrp_60d.

    Args:
        daily_returns: SPY daily returns (≥5 obs required, 60+ for primary metric).
        vix_level: current VIX (e.g., 20.0 for 20%). None → vrp=0.
        as_of: report date.

    Returns:
        RealVolSnapshot or None on empty/short/exception (D8).
    """
    try:
        if daily_returns is None or daily_returns.empty or len(daily_returns) < 5:
            logger.warning(
                "Realized vol: insufficient returns (%d obs) — F7/F9 skipped",
                len(daily_returns) if daily_returns is not None else 0,
            )
            return None

        # Annualized stddev
        realized_60d = float(daily_returns.tail(60).std() * np.sqrt(252))
        realized_20d = float(daily_returns.tail(20).std() * np.sqrt(252))

        # VRP — variance risk premium
        vrp = 0.0
        if vix_level is not None and vix_level > 0:
            vix_var = (vix_level / 100.0) ** 2
            realized_var = realized_60d ** 2
            vrp = (vix_var - realized_var) * 10000.0

        return RealVolSnapshot(
            realized_vol_60d=realized_60d,
            realized_vol_20d=realized_20d,
            vrp_60d=vrp,
            source_date=as_of,
        )
    except Exception as e:
        logger.warning("Realized vol compute failed: %s", e)
        return None
