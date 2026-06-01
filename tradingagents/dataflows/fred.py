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
    # Backtest fallback (2026-05-26): ICE BofA 4 OAS series 가 FRED 의 "3-year-only"
    # 정책 (2026-04~) 으로 2023-05-23 부터만 가용. 이전 시점 backtest 위해 Moody's
    # BAA - 10Y Treasury spread 사용 (1986-, daily, FRED 무료, 단위 % 동일).
    # IG/HY/BBB 모두 같은 BAA10Y 사용 — 의미상 비슷 (모두 credit spread 측정).
    # AAA 도 sentinel 대비 BAA10Y 가 더 나은 proxy.
    # backtest/data.py:24 와 같은 패턴.
    "us_credit_proxy": "BAA10Y",       # Moody's BAA - 10Y, daily 1986-
    # === Tier 0 additions (2026-05-28) ===
    # F1 reform — INDPRO + Real PCE replace nfci/curve removal
    "us_indpro": "INDPRO",                # Industrial Production Index (1919+)
    "us_real_pce": "PCECC96",             # Real PCE Chained 2017 Dollars (1947+, quarterly)
    # F4 reform — ACM term premium decomposition
    "us_acm_term_premium_10y": "THREEFYTP10",  # NY Fed 10y ACM (1990+, daily)
    # F6 reform — BIS REER (Engel-West random walk fix companion)
    "kr_reer": "RBKRBIS",                 # BIS Real Effective Exchange Rate KR (1994+, monthly)
    # F10 SOFR-TED stitching (pre-2018 proxy)
    "ted_spread": "TEDRATE",              # TED Spread (1986-2022, discontinued)
}


# Backtest fix (2026-05-26): historical 시점 (2023-05 이전) FRED 빈 결과 시 fallback.
# fetch_fred_series 가 자동 시도. caller 코드 변경 불필요.
FRED_FALLBACK_CHAIN: dict[str, str] = {
    "us_ig_oas": "us_credit_proxy",    # BAMLC0A0CM → BAA10Y
    "us_hy_oas": "us_credit_proxy",    # BAMLH0A0HYM2 → BAA10Y (HY proxy 약간 약함)
    "us_aaa_oas": "us_credit_proxy",   # BAMLC0A1CAAA → BAA10Y (proxy)
    "us_bbb_oas": "us_credit_proxy",   # BAMLC0A4CBBB → BAA10Y (BBB ≈ BAA 동급)
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

    # Backtest fallback (2026-05-26): empty Series + fallback 가능한 series 면
    # FRED_FALLBACK_CHAIN 으로 자동 대체. caller 코드 변경 없이 historical 시점
    # 정상 동작 (BAMLC0A0CM 등 FRED 3-year 정책 회피).
    if (series is None or series.empty) and series_id in FRED_FALLBACK_CHAIN:
        fallback_id = FRED_FALLBACK_CHAIN[series_id]
        fallback_resolved = FRED_SERIES.get(fallback_id, fallback_id)
        logger.warning(
            "FRED %s (%s) empty (likely 3-year policy or retired) → fallback %s (%s)",
            series_id, resolved, fallback_id, fallback_resolved,
        )
        try:
            series = _raw_fred_call(fallback_resolved, start, end, key)
        except Exception as e:
            logger.warning(
                "FRED fallback %s also failed: %s — returning empty",
                fallback_id, e,
            )
            series = None

    # Backtest fix (2026-05-26): empty Series 에서 RangeIndex AttributeError 방지.
    # FRED 일부 series (예: BAMLC0A0CM 은 2023-05-23 이후 데이터만) 가 historical
    # 시점에 빈 결과 반환 → series.index 가 RangeIndex → `.date` AttributeError.
    if series is None or series.empty:
        return pd.Series(dtype=float, name=series_id)

    if as_of_date is not None:
        cutoff = _publication_cutoff(as_of_date, series_id)
        # DatetimeIndex 검증 — 비정상 케이스 graceful 처리.
        if hasattr(series.index, "date"):
            series = series[series.index.date <= cutoff]
            logger.debug(
                "FRED %s point-in-time cutoff %s (as_of=%s, lag applied)",
                series_id, cutoff, as_of_date,
            )
        else:
            logger.warning(
                "FRED %s returned non-DatetimeIndex (type=%s) — cutoff skip, return empty",
                series_id, type(series.index).__name__,
            )
            return pd.Series(dtype=float, name=series_id)

    return series


def fetch_funding_stress_stitched(
    start: date, end: date, as_of_date: date | None = None,
) -> pd.Series:
    """SOFR-Tbill (2018+) + TED (1986-2018-04-03) stitched series, in bps.

    F10 systemic_liquidity's sofr_tbill_spread component.
    Stitch boundary: 2018-04-03 (SOFR introduction, hard switch).
    Overlap (2018-04 ~ 2022-01) uses SOFR-Tbill (TED discontinued 2022).

    Note: regime-aware z-baseline handled separately in
    factor_baselines_dynamic.compute_expanding_baseline_funding_stress.
    """
    boundary = date(2018, 4, 3)
    pieces: list[pd.Series] = []

    if start < boundary:
        ted_end = min(end, date(2018, 4, 2))
        ted = fetch_fred_series("ted_spread", start, ted_end, as_of_date=as_of_date)
        # Defensive: drop anything at/after boundary
        if not ted.empty:
            ted = ted[ted.index < pd.Timestamp(boundary)]
        pieces.append(ted)

    if end >= boundary:
        sofr_start = max(start, boundary)
        sofr = fetch_fred_series("us_sofr", sofr_start, end, as_of_date=as_of_date)
        tbill = fetch_fred_series("us_3m_tbill", sofr_start, end, as_of_date=as_of_date)
        # Align indexes (both daily). Convert percent → bps.
        common = sofr.index.intersection(tbill.index)
        sofr_tbill = (sofr.loc[common] - tbill.loc[common]) * 100
        pieces.append(sofr_tbill)

    if not pieces:
        return pd.Series(dtype=float, name="funding_stress_bps")
    result = pd.concat(pieces).sort_index()
    result.name = "funding_stress_bps"
    return result
