"""Benchmark bucket weight generators for PR2b validation.

5 strategies:
1. equal_weight (1/N)
2. kr_tilted_60_40 (60-40 KR-tilted)
3. risk_parity (σ-inverse, 60Q rolling cov)
4. (calibrated PR2a — uses INITIAL_BETA via factor_to_bucket.apply_factor_model)
5. (hand-coded prior — HAND_CODED_BETA_PR2A_PRE → apply_factor_model with beta=...)

24-cell legacy 는 별도 wrapper (cell_24_legacy) 에서 optimize.fit_all 호출.
"""
from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_to_bucket import BUCKETS, FACTORS


# Pre-PR2a hand-coded INITIAL_BETA snapshot (from git commit 3572d03).
# Used as a benchmark in PR2b validation. PR2a 가 main 의 INITIAL_BETA 를
# calibrated 로 교체했으므로 git history snapshot 을 inline literal 로 보존.
HAND_CODED_BETA_PR2A_PRE: Final[dict[tuple[str, str], float]] = {
    # F1 growth (+z = growth → +equity, -bond)
    ("F1_growth", "kr_equity"):     +0.04,
    ("F1_growth", "global_equity"): +0.06,
    ("F1_growth", "fx_commodity"):  +0.01,
    ("F1_growth", "bond"):          -0.08,
    ("F1_growth", "cash_mmf"):      -0.03,
    # F2 inflation
    ("F2_inflation", "kr_equity"):     -0.02,
    ("F2_inflation", "global_equity"): -0.03,
    ("F2_inflation", "fx_commodity"):  +0.07,
    ("F2_inflation", "bond"):          -0.05,
    ("F2_inflation", "cash_mmf"):      +0.03,
    # F3 real_rate
    ("F3_real_rate", "kr_equity"):     -0.02,
    ("F3_real_rate", "global_equity"): -0.03,
    ("F3_real_rate", "fx_commodity"):  -0.01,
    ("F3_real_rate", "bond"):          -0.05,
    ("F3_real_rate", "cash_mmf"):      +0.11,
    # F4 term_premium
    ("F4_term_premium", "kr_equity"):     +0.02,
    ("F4_term_premium", "global_equity"): +0.03,
    ("F4_term_premium", "fx_commodity"):  0.0,
    ("F4_term_premium", "bond"):          +0.02,
    ("F4_term_premium", "cash_mmf"):      -0.07,
    # F5 credit_cycle
    ("F5_credit_cycle", "kr_equity"):     -0.05,
    ("F5_credit_cycle", "global_equity"): -0.06,
    ("F5_credit_cycle", "fx_commodity"):  +0.01,
    ("F5_credit_cycle", "bond"):          -0.02,
    ("F5_credit_cycle", "cash_mmf"):      +0.12,
    # F6 krw_regime
    ("F6_krw_regime", "kr_equity"):     -0.05,
    ("F6_krw_regime", "global_equity"): +0.04,
    ("F6_krw_regime", "fx_commodity"):  +0.03,
    ("F6_krw_regime", "bond"):          -0.01,
    ("F6_krw_regime", "cash_mmf"):      -0.01,
    # F7 equity_vol_regime
    ("F7_equity_vol_regime", "kr_equity"):     -0.04,
    ("F7_equity_vol_regime", "global_equity"): -0.06,
    ("F7_equity_vol_regime", "fx_commodity"):  -0.02,
    ("F7_equity_vol_regime", "bond"):          +0.04,
    ("F7_equity_vol_regime", "cash_mmf"):      +0.08,
    # F8 valuation
    ("F8_valuation", "kr_equity"):     -0.03,
    ("F8_valuation", "global_equity"): -0.04,
    ("F8_valuation", "fx_commodity"):  +0.01,
    ("F8_valuation", "bond"):          +0.04,
    ("F8_valuation", "cash_mmf"):      +0.02,
    # F9 market_dispersion (renamed from F9_liquidity_regime, Tier 0 2026-05-28)
    ("F9_market_dispersion", "kr_equity"):     -0.03,
    ("F9_market_dispersion", "global_equity"): -0.05,
    ("F9_market_dispersion", "fx_commodity"):  -0.01,
    ("F9_market_dispersion", "bond"):          +0.04,
    ("F9_market_dispersion", "cash_mmf"):      +0.05,
    # F10 systemic_liquidity (2026-05-27 신규)
    ("F10_systemic_liquidity", "kr_equity"):     -0.04,
    ("F10_systemic_liquidity", "global_equity"): -0.05,
    ("F10_systemic_liquidity", "fx_commodity"):  -0.01,
    ("F10_systemic_liquidity", "bond"):          +0.05,
    ("F10_systemic_liquidity", "cash_mmf"):      +0.05,
}


def equal_weight() -> dict[str, float]:
    """1/N: 각 bucket = 1/len(BUCKETS) = 0.2."""
    n = len(BUCKETS)
    return {b: 1.0 / n for b in BUCKETS}


def kr_tilted_60_40() -> dict[str, float]:
    """60-40 KR-tilted static: kr_eq 0.20 + gl_eq 0.40 + bond 0.40.

    PR2a 의 benchmark_60_40_returns 의 weight 와 동일.
    """
    return {
        "kr_equity": 0.20,
        "global_equity": 0.40,
        "fx_commodity": 0.0,
        "bond": 0.40,
        "cash_mmf": 0.0,
    }


def risk_parity(
    returns: pd.DataFrame,
    window: int = 60,
) -> dict[str, float]:
    """σ-inverse weighted (simple risk parity), 60Q rolling std.

    Args:
        returns: bucket × time DataFrame (columns = BUCKETS, rows = quarter).
        window: rolling window size (default 60Q).

    Returns:
        weight dict summing to 1.0. Higher weight for lower-σ bucket.

    Note: 완전한 risk parity (HRP) 가 아닌 1/σ 단순 weighting. PR2b 의 목적
    상 simple risk parity 가 충분 (benchmark 비교용, optimization aim 아님).
    """
    if returns.empty:
        return equal_weight()
    tail = returns.tail(window) if len(returns) >= window else returns
    sigmas = {b: float(tail[b].std(ddof=1)) for b in BUCKETS if b in tail.columns}
    inv_sigmas = {b: 1.0 / max(s, 1e-6) for b, s in sigmas.items()}
    total = sum(inv_sigmas.values())
    if total <= 0:
        return equal_weight()
    return {b: inv_sigmas.get(b, 0.0) / total for b in BUCKETS}
