"""Expanding window z-score normalization (Pesaran-Timmermann 1995 JF).

Replaces static LONG_RUN_BASELINE with time-honest expanding mean/sd.
Per-component dispatch table maps component → (source_type, fetcher_callable).

Cache: data/cache/factor_history/{component}.parquet, weekly TTL.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Final

import pandas as pd

from tradingagents.skills.research.factor_baselines import get_baseline

logger = logging.getLogger(__name__)

CACHE_DIR: Final[Path] = Path("data/cache/factor_history")
CACHE_TTL_DAYS: Final[int] = 7
MIN_HISTORY_POINTS: Final[int] = 60


def _yoy_pct(series: pd.Series) -> pd.Series:
    """Year-over-year %-change (monthly data assumed)."""
    return (series / series.shift(12) - 1.0) * 100


def _pct_change_n(series: pd.Series, n: int) -> pd.Series:
    return (series / series.shift(n) - 1.0) * 100


def _zscore_60m(series: pd.Series) -> pd.Series:
    return (series - series.rolling(60).mean()) / series.rolling(60).std()


COMPONENT_HISTORY_SOURCES: dict[str, tuple[str, Callable]] = {}


def _register_default_sources() -> None:
    """Populate dispatch table — lazy to avoid circular imports."""
    if COMPONENT_HISTORY_SOURCES:
        return
    from tradingagents.dataflows import fred
    from tradingagents.dataflows import shiller_cape, gpr_index, gz_ebp, bis_credit

    COMPONENT_HISTORY_SOURCES.update({
        # FRED direct
        "cfnai":    ("fred", lambda s, e: fred.fetch_fred_series("us_cfnai", s, e)),
        "cfnai_3m": ("fred", lambda s, e: fred.fetch_fred_series("us_cfnai_ma3", s, e)),
        "vix_level":("fred", lambda s, e: fred.fetch_fred_series("vix_close", s, e)),
        "move":     ("fred", lambda s, e: fred.fetch_fred_series("move", s, e)),
        "tips_yield": ("fred", lambda s, e: fred.fetch_fred_series("us_tips_10y", s, e)),
        "acm_term_premium_10y": ("fred",
            lambda s, e: fred.fetch_fred_series("us_acm_term_premium_10y", s, e)),
        "five_y_five_y": ("fred",
            lambda s, e: fred.fetch_fred_series("us_5y5y_breakeven", s, e)),
        "michigan_1y":   ("fred",
            lambda s, e: fred.fetch_fred_series("us_michigan_1y", s, e)),
        # FRED derived
        "indpro_yoy":   ("fred_derived",
            lambda s, e: _yoy_pct(fred.fetch_fred_series("us_indpro", s, e))),
        "real_pce_yoy": ("fred_derived",
            lambda s, e: _yoy_pct(fred.fetch_fred_series("us_real_pce", s, e))),
        "krw_change_6m_pct": ("fred_derived",
            lambda s, e: _pct_change_n(fred.fetch_fred_series("usd_krw", s, e), 126)),
        "krw_reer": ("fred", lambda s, e: fred.fetch_fred_series("kr_reer", s, e)),
        # External CSV (TTL cached)
        "us_cape":     ("shiller",  lambda s, e: shiller_cape.fetch_shiller_cape(as_of=e)),
        "gpr_index_zscore": ("iacoviello_derived",
            lambda s, e: _zscore_60m(gpr_index.fetch_gpr_index("monthly", as_of=e))),
        "gz_ebp":      ("fed_board", lambda s, e: gz_ebp.fetch_gz_ebp(as_of=e)),
        # BIS
        "credit_impulse": ("bis_derived",
            lambda s, e: bis_credit.fetch_bis_china_credit(as_of=e)),
    })


def _cache_path(component: str) -> Path:
    return CACHE_DIR / f"{component}.parquet"


def _read_cache(component: str, start: date, end: date) -> pd.Series | None:
    path = _cache_path(component)
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    if (datetime.now() - mtime).days >= CACHE_TTL_DAYS:
        return None
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        logger.warning("cache read %s failed: %s", component, e)
        return None
    if "value" not in df.columns:
        return None
    s = df.set_index(df.columns[0])["value"]
    s.index = pd.to_datetime(s.index)
    return s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]


def _write_cache(component: str, series: pd.Series) -> None:
    path = _cache_path(component)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = series.rename("value").reset_index()
    df.columns = ["date", "value"]
    df.to_parquet(path, index=False)


def _fetch_with_cache(component: str, start: date, end: date) -> pd.Series | None:
    cached = _read_cache(component, start, end)
    if cached is not None and len(cached) > 0:
        return cached
    if component not in COMPONENT_HISTORY_SOURCES:
        return None
    _, fetcher = COMPONENT_HISTORY_SOURCES[component]
    try:
        series = fetcher(start, end)
        if series is not None and len(series) > 0:
            try:
                _write_cache(component, series)
            except Exception as e:
                logger.warning("cache write %s failed: %s", component, e)
        return series
    except Exception as e:
        logger.warning("factor_baselines_dynamic fetch %s failed: %s", component, e)
        return None


def compute_expanding_baseline(
    component: str,
    factor: str,
    as_of_date: date,
    history_start: date = date(1971, 1, 1),
) -> tuple[float, float] | None:
    """Returns (mean, sd) computed from history_start to as_of_date.

    Routes special-case 'funding_bps' to compute_expanding_baseline_funding_stress.
    Falls back to static LONG_RUN_BASELINE if:
    - component not in dispatch table
    - fetch fails
    - n < MIN_HISTORY_POINTS (60)
    """
    # Task 8.2: special case
    if component == "funding_bps":
        return compute_expanding_baseline_funding_stress(as_of_date)

    _register_default_sources()
    if component not in COMPONENT_HISTORY_SOURCES:
        return get_baseline(factor, component)
    series = _fetch_with_cache(component, history_start, as_of_date)
    if series is None or len(series) < MIN_HISTORY_POINTS:
        return get_baseline(factor, component)
    s_clean = series.dropna()
    if len(s_clean) < MIN_HISTORY_POINTS:
        return get_baseline(factor, component)
    return float(s_clean.mean()), float(s_clean.std(ddof=1))


# Task 8.2: Regime-aware funding stress (SOFR-TED stitching)
def compute_expanding_baseline_funding_stress(
    as_of_date: date,
) -> tuple[float, float]:
    """Regime-aware: pre-2018-04-03 uses TED moments, post uses SOFR-Tbill moments.

    Reason: TED (~30bps mean) and SOFR-Tbill (~5bps mean) different scales —
    unified mean/sd would bias z-scores in either regime.
    """
    from tradingagents.dataflows import fred
    boundary = date(2018, 4, 3)
    if as_of_date < boundary:
        try:
            ted = fred.fetch_fred_series("ted_spread", date(1986, 1, 1), as_of_date)
            if len(ted) < MIN_HISTORY_POINTS:
                return (30.0, 30.0)  # static prior
            return float(ted.mean()), float(ted.std(ddof=1))
        except Exception as e:
            logger.warning("TED baseline fetch failed: %s", e)
            return (30.0, 30.0)
    else:
        try:
            from tradingagents.dataflows.fred import fetch_funding_stress_stitched
            s = fetch_funding_stress_stitched(date(2018, 4, 3), as_of_date)
            if len(s) < MIN_HISTORY_POINTS:
                return (5.0, 10.0)
            return float(s.mean()), float(s.std(ddof=1))
        except Exception as e:
            logger.warning("SOFR-Tbill baseline fetch failed: %s", e)
            return (5.0, 10.0)


__all__ = [
    "compute_expanding_baseline",
    "compute_expanding_baseline_funding_stress",
    "COMPONENT_HISTORY_SOURCES",
    "CACHE_DIR",
    "MIN_HISTORY_POINTS",
]
