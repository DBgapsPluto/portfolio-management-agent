"""F12 China Credit Impulse — Biggs-Mayer-Pick 2010 JMCB.

CI(t) = (Δ_t - Δ_{t-4}) / credit_{t-4} × 100
where Δ_t = credit_to_gdp_t - credit_to_gdp_{t-1}

Source: BIS Total Credit Q:CN:P:A:M:770:A (quarterly, % of GDP).
"""
from __future__ import annotations

import logging
from datetime import date

from tradingagents.dataflows.bis_credit import fetch_bis_china_credit

logger = logging.getLogger(__name__)


def compute_china_credit_impulse(as_of: date) -> dict[str, float] | None:
    """Returns dict with 'impulse', 'ratio', 'yoy' keys, or None if insufficient history (<6 quarters)."""
    try:
        series = fetch_bis_china_credit(as_of=as_of)
    except Exception as e:
        logger.warning("BIS fetch failed: %s", e)
        return None
    if series is None or len(series) < 6:
        return None

    s = series.tail(6).values
    # s = [ratio_{t-5}, ratio_{t-4}, ratio_{t-3}, ratio_{t-2}, ratio_{t-1}, ratio_{t}]
    delta_t = s[-1] - s[-2]
    delta_t_minus_4 = s[-5] - s[-6]
    credit_t_minus_4 = s[-5]
    if credit_t_minus_4 == 0:
        return None
    impulse = (delta_t - delta_t_minus_4) / credit_t_minus_4 * 100.0
    yoy = (s[-1] / s[-5] - 1.0) * 100.0 if s[-5] != 0 else 0.0
    return {
        "impulse": float(impulse),
        "ratio":   float(s[-1]),
        "yoy":     float(yoy),
    }


__all__ = ["compute_china_credit_impulse"]
