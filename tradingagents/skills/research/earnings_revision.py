"""F11 Earnings Revision Net Ratio aggregation.

Source: yfinance ticker.upgrades_downgrades (SP500) + pykrx PER 1m change (KOSPI200).
Reference: Chan-Jegadeesh-Lakonishok 1996 JF, Asness-Frazzini-Pedersen 2019.
Backtest coverage: 2010+ (yfinance API limit) — staggered calibration in Tier 2.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

SP500_CONSTITUENTS_PATH: Final[Path] = Path("data/universe/sp500_constituents.json")


def load_sp500_constituents() -> list[str]:
    if not SP500_CONSTITUENTS_PATH.exists():
        logger.warning("SP500 constituents file missing: %s", SP500_CONSTITUENTS_PATH)
        return []
    with open(SP500_CONSTITUENTS_PATH) as f:
        return json.load(f)


def compute_sp500_net_revision(
    as_of: date, lookback_days: int = 30, coverage_threshold: float = 0.5,
) -> float | None:
    """SP500 net revision proxy via yfinance upgrades_downgrades."""
    constituents = load_sp500_constituents()
    if not constituents:
        return None
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=lookback_days)
    total_up, total_down, n_valid = 0, 0, 0
    for ticker in constituents:
        try:
            ud = yf.Ticker(ticker).upgrades_downgrades
            if ud is None or ud.empty:
                continue
            ud_idx = ud.index if isinstance(ud.index, pd.DatetimeIndex) else pd.to_datetime(ud.index)
            recent = ud[ud_idx >= cutoff]
            ups = (recent["Action"].astype(str).str.lower() == "upgrade").sum()
            downs = (recent["Action"].astype(str).str.lower() == "downgrade").sum()
            if ups + downs > 0:
                total_up += int(ups)
                total_down += int(downs)
                n_valid += 1
        except Exception as e:
            logger.debug("yfinance %s skip: %s", ticker, e)
            continue
    if n_valid < len(constituents) * coverage_threshold:
        return None
    total = total_up + total_down
    return (total_up - total_down) / total if total > 0 else 0.0


def compute_kospi200_net_revision(as_of: date) -> float | None:
    """KOSPI200 forward EPS implied 1m change via pykrx fundamentals."""
    try:
        from pykrx import stock as pkstock
    except ImportError:
        logger.warning("pykrx not available — KOSPI net_revision returns None")
        return None
    month_ago = as_of - timedelta(days=30)
    try:
        today_fund = pkstock.get_market_fundamental_by_date(
            as_of.strftime("%Y%m%d"), as_of.strftime("%Y%m%d"), market="KOSPI"
        )
        prior_fund = pkstock.get_market_fundamental_by_date(
            month_ago.strftime("%Y%m%d"), month_ago.strftime("%Y%m%d"), market="KOSPI"
        )
        kospi200 = pkstock.get_index_portfolio_deposit_file("1028")
    except Exception as e:
        logger.warning("pykrx fetch failed: %s", e)
        return None

    n_up, n_down, n_valid = 0, 0, 0
    for ticker in kospi200:
        if ticker not in today_fund.index or ticker not in prior_fund.index:
            continue
        t_per = today_fund.loc[ticker, "PER"]
        p_per = prior_fund.loc[ticker, "PER"]
        if not (t_per > 0 and p_per > 0):
            continue
        # Forward EPS = 1/PER. Lower PER (same price) = higher EPS = upward revision.
        eps_pct_change = (1.0 / t_per - 1.0 / p_per) / (1.0 / p_per)
        if eps_pct_change > 0.01:
            n_up += 1
        elif eps_pct_change < -0.01:
            n_down += 1
        n_valid += 1
    if n_valid < 100:
        return None
    total = n_up + n_down
    return (n_up - n_down) / total if total > 0 else 0.0


__all__ = ["compute_sp500_net_revision", "compute_kospi200_net_revision", "load_sp500_constituents"]
