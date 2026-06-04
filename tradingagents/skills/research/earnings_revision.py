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


def _kospi_fundamental_at(pkstock, target: date, max_back: int = 7):
    """target 이하 가장 가까운 거래일의 KOSPI fundamental df. 없으면 None.

    휴장일(주말/공휴일)은 pykrx 가 행은 주지만 PER 전부 0 으로 반환 → PER>0 이
    하나도 없으면 무효로 보고 하루씩 뒤로 물러난다 (최대 max_back 일).
    """
    d = target
    for _ in range(max_back + 1):
        try:
            df = pkstock.get_market_fundamental(d.strftime("%Y%m%d"), market="KOSPI")
        except Exception:
            df = None
        if df is not None and not df.empty and (df["PER"] > 0).any():
            return df
        d -= timedelta(days=1)
    return None


def compute_kospi200_net_revision(as_of: date) -> float | None:
    """KOSPI forward EPS implied 1m revision breadth via pykrx fundamentals.

    get_market_fundamental_by_date(market=) 는 설치된 pykrx 가 market= 미지원이라
    깨짐. KOSPI200 구성종목(get_index_portfolio_deposit_file)도 KRX schema 변경으로
    빈 응답 → 둘 다 의존 제거하고, 작동하는 get_market_fundamental 로 전체 KOSPI
    종목 PER 교집합에서 revision breadth 를 계산 (KOSPI200 proxy).
    """
    try:
        from pykrx import stock as pkstock
    except ImportError:
        logger.warning("pykrx not available — KOSPI net_revision returns None")
        return None
    month_ago = as_of - timedelta(days=30)
    today_fund = _kospi_fundamental_at(pkstock, as_of)
    prior_fund = _kospi_fundamental_at(pkstock, month_ago)
    if today_fund is None or prior_fund is None:
        return None

    n_up, n_down, n_valid = 0, 0, 0
    for ticker in today_fund.index.intersection(prior_fund.index):
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
