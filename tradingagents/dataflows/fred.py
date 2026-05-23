import logging
import os
from datetime import date, timedelta

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


FRED_SERIES = {
    "us_10y": "DGS10",
    "us_2y": "DGS2",
    "us_3m": "DGS3MO",
    # 2026-05-23 C4: 5y + 30y Treasury yields — F4 term_premium (5-30y long-end slope)
    "us_5y": "DGS5",
    "us_30y": "DGS30",
    "us_cpi": "CPIAUCSL",
    "us_core_cpi": "CPILFESL",
    # PCE deflator — Fed의 공식 inflation 타겟. 2026-05 추가.
    "us_pce": "PCEPI",                 # Personal Consumption Expenditures Price Index
    "us_core_pce": "PCEPILFE",         # Core PCE (ex food & energy) — Fed 핵심 모니터링
    "us_unrate": "UNRATE",
    "us_payems": "PAYEMS",
    "us_lfpr": "CIVPART",              # Labor Force Participation Rate (2026-05 Sahm cross-check)
    # JOLTS — labor market tightness leading indicator (2026-05 추가).
    "us_jolts_openings": "JTSJOL",     # Job Openings (level, thousands)
    "us_jolts_quits": "JTSQUR",        # Quits Rate (% of employment)
    "us_jolts_hires": "JTSHIR",        # Hires Rate (% — supplementary)
    "fed_balance_sheet": "WALCL",
    "us_policy_rate": "DFF",
    "us_ig_oas": "BAMLC0A0CM",
    "us_hy_oas": "BAMLH0A0HYM2",
    "vix_close": "VIXCLS",
    # Tier-1 확장: 선행지표 + 실시간 GDP nowcast
    "us_cfnai": "CFNAI",               # Chicago Fed National Activity Index (single month)
    "us_cfnai_ma3": "CFNAIMA3",        # 3-month MA; <-0.7 = recession entry
    "us_gdp_nowcast": "GDPNOW",        # Atlanta Fed real-time GDP nowcast (% annualized)
    # Tier-2 확장: financial conditions + 기대 인플레 + Fed path proxy
    "us_nfci": "NFCI",                 # Chicago Fed National Financial Conditions (weekly)
    "us_anfci": "ANFCI",               # Adjusted NFCI (background macro removed)
    "us_5y5y_breakeven": "T5YIFR",     # 5Y5Y forward breakeven inflation
    "us_michigan_1y": "MICH",          # Univ of Michigan 1y inflation expectation
    "us_1y_yield": "DGS1",             # 1y Treasury yield (Fed path 보조 proxy)
    # Tier-3 확장: cross-asset risk-on/off
    "usd_krw": "DEXKOUS",              # KRW per USD (daily)
    "dxy": "DTWEXBGS",                 # Trade-weighted broad dollar index (daily)
    "china_cli": "CHNLOLITONOSTSAM",   # OECD China amplitude-adjusted CLI (monthly)
    # Tier-4 확장: Policy uncertainty + Tail risk
    "us_epu": "USEPUINDXM",            # Baker-Bloom-Davis US Economic Policy Uncertainty (monthly)
    "global_epu": "GEPUCURRENT",       # Global EPU current-price weighted (monthly)
    "vvix": "VVIXCLS",                 # CBOE VIX of VIX (daily)
    "move": "MOVE",                    # ICE BofA MOVE Index (Treasury vol, daily)
    # market_risk Tier-1 확장: equity stress 깊이
    "vix_3m": "VXVCLS",                # CBOE VIX 3-month (daily)
    "vxn": "VXNCLS",                   # CBOE NASDAQ-100 Volatility (daily)
    # market_risk Tier-2 확장: bond/funding stress
    "us_tips_10y": "DFII10",           # 10-Year TIPS yield (real, %)
    "us_tips_5y": "DFII5",             # 5-Year TIPS yield (real, %)
    "us_sofr": "SOFR",                 # Secured Overnight Financing Rate (%)
    "us_3m_tbill": "DTB3",             # 3-month Treasury bill yield (%)
    "us_aaa_oas": "BAMLC0A1CAAA",      # ICE BofA AAA Corporate OAS (%)
    "us_bbb_oas": "BAMLC0A4CBBB",      # ICE BofA BBB Corporate OAS (%)
}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_fred_call(series_id: str, start: date, end: date, api_key: str) -> pd.Series:
    """Wrapped for mocking + transient retry."""
    from fredapi import Fred
    fred = Fred(api_key=api_key)
    return fred.get_series(series_id, observation_start=start, observation_end=end)


def _publication_cutoff(as_of_date: date, friendly_key: str) -> date:
    """Latest data point that was actually published by as_of_date.

    Look-ahead bias prevention: e.g., May CPI is released ~mid-June, so a
    simulation with as_of=2026-05-25 must NOT see May CPI.
    """
    lag = DEFAULT_CONFIG["publication_lag_days"].get(friendly_key, 1)
    return as_of_date - timedelta(days=lag)


def fetch_fred_series(
    series_id: str, start: date, end: date, api_key: str | None = None,
    as_of_date: date | None = None,
) -> pd.Series:
    """Fetch a single FRED series with point-in-time integrity.

    Args:
        as_of_date: If provided, truncates to data published by that date
            (publication lag applied per DEFAULT_CONFIG['publication_lag_days']).
            None means use raw end (live mode).
    """
    key = api_key or os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY not set")

    resolved = FRED_SERIES.get(series_id, series_id)
    series = _raw_fred_call(resolved, start, end, key)

    if as_of_date is not None:
        cutoff = _publication_cutoff(as_of_date, series_id)
        series = series[series.index.date <= cutoff]
        logger.debug(
            "FRED %s point-in-time cutoff %s (as_of=%s, lag applied)",
            series_id, cutoff, as_of_date,
        )

    return series
