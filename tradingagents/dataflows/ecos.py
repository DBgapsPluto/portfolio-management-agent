import logging
import os
from datetime import date, timedelta

import pandas as pd
import requests
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


# 한국은행 ECOS 통계코드 (2026 기준 — 코드 변경 가능)
ECOS_STAT_CODES = {
    "kr_base_rate": ("722Y001", "0101000"),
    "kr_cpi": ("901Y009", "0"),
    "kr_m2": ("101Y004", "BBHA00"),
    "kr_export": ("403Y001", "*AA"),
    "kr_import": ("403Y003", "*AA"),
    "kr_industrial_production": ("901Y033", "*"),
    "kr_unrate": ("901Y027", "I31A"),
}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
)
def _raw_ecos_call(
    stat_code: str, item_code: str, freq: str,
    start: str, end: str, api_key: str,
) -> dict:
    """Direct ECOS REST call. Wrapped for mocking + retry."""
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/1000/"
        f"{stat_code}/{freq}/{start}/{end}/{item_code}"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def _ecos_publication_cutoff(as_of_date: date, friendly_key: str) -> date:
    """ECOS publication-lag cutoff (look-ahead bias prevention)."""
    lag = DEFAULT_CONFIG["publication_lag_days"].get(friendly_key, 5)
    return as_of_date - timedelta(days=lag)


def fetch_ecos_series(
    name: str, start: date, end: date, api_key: str | None = None,
    freq: str = "M", as_of_date: date | None = None,
) -> pd.Series:
    """Fetch a Bank of Korea ECOS series by friendly name.

    Frequency codes: M=월, Q=분기, A=연.
    """
    key = api_key or os.environ.get("ECOS_API_KEY")
    if not key:
        raise RuntimeError("ECOS_API_KEY not set")
    if name not in ECOS_STAT_CODES:
        raise KeyError(f"unknown ECOS series: {name!r}")

    stat_code, item_code = ECOS_STAT_CODES[name]
    fmt = "%Y%m" if freq in ("M", "Q") else "%Y"
    payload = _raw_ecos_call(
        stat_code, item_code, freq,
        start.strftime(fmt), end.strftime(fmt), key,
    )

    rows = payload.get("StatisticSearch", {}).get("row", [])
    if not rows:
        return pd.Series(dtype=float, name=name)

    times = []
    values = []
    for row in rows:
        t = row["TIME"]
        if freq == "M":
            ts = pd.Timestamp(year=int(t[:4]), month=int(t[4:6]), day=1)
        else:
            ts = pd.Timestamp(year=int(t[:4]), month=1, day=1)
        times.append(ts)
        values.append(float(row["DATA_VALUE"]))
    series = pd.Series(values, index=times, name=name)

    if as_of_date is not None:
        cutoff = _ecos_publication_cutoff(as_of_date, name)
        series = series[series.index.date <= cutoff]

    return series
