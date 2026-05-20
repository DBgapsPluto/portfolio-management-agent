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


# 한국은행 ECOS 통계코드. item_code는 str 또는 tuple (다층 dimension).
# tuple로 주면 URL path segment로 "/".join 되어 들어감 (예: BSI 산업/지표 2단계).
ECOS_STAT_CODES: dict[str, tuple[str, str | tuple[str, ...]]] = {
    "kr_base_rate": ("722Y001", "0101000"),
    "kr_cpi": ("901Y009", "0"),
    "kr_m2": ("101Y004", "BBHA00"),
    "kr_export": ("403Y001", "*AA"),
    "kr_import": ("403Y003", "*AA"),
    "kr_industrial_production": ("901Y033", "*"),
    "kr_unrate": ("901Y027", "I31A"),
    # Tier-1 확장 — KR 경기 사이클 신호
    "kr_cli": ("901Y067", "I16D"),       # 선행지수 순환변동치
    # 512Y014 = 기업경기실사지수(BSI), 산업(X8000=제조업) + 지표(BA=업황실적BSI) 2-step.
    "kr_bsi_mfg": ("512Y014", ("X8000", "BA")),
    # market_risk Tier-3 — KR-specific risk
    # 817Y002 = 시장금리(일별), item code는 종목별 (ECOS 카탈로그 확인 완료, 2026-05)
    "kr_treasury_3y": ("817Y002", "010200000"),     # 국고채(3년) — 010195000은 2년
    "kr_treasury_10y": ("817Y002", "010210000"),    # 국고채(10년)
    "kr_corp_aa_3y": ("817Y002", "010300000"),      # 회사채(3년, AA-) — 010320000은 BBB-
}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
)
def _raw_ecos_call(
    stat_code: str, item_code: str | tuple[str, ...], freq: str,
    start: str, end: str, api_key: str,
) -> dict:
    """Direct ECOS REST call. Wrapped for mocking + retry.

    item_code: str → single dim; tuple → multi-dim (joined with /).
    """
    item_path = "/".join(item_code) if isinstance(item_code, tuple) else item_code
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/10000/"
        f"{stat_code}/{freq}/{start}/{end}/{item_path}"
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
    if freq == "D":
        fmt = "%Y%m%d"
    elif freq in ("M", "Q"):
        fmt = "%Y%m"
    else:
        fmt = "%Y"
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
        if freq == "D":
            ts = pd.Timestamp(year=int(t[:4]), month=int(t[4:6]), day=int(t[6:8]))
        elif freq == "M":
            ts = pd.Timestamp(year=int(t[:4]), month=int(t[4:6]), day=1)
        elif freq == "Q":
            # ECOS quarterly TIME: YYYYQQ where QQ ∈ {1,2,3,4} or YYYYMM
            if len(t) == 5:  # YYYYQ
                q = int(t[4])
                ts = pd.Timestamp(year=int(t[:4]), month=(q - 1) * 3 + 1, day=1)
            else:  # treat as monthly stamp
                ts = pd.Timestamp(year=int(t[:4]), month=int(t[4:6]), day=1)
        else:
            ts = pd.Timestamp(year=int(t[:4]), month=1, day=1)
        # DATA_VALUE may be empty string for missing observations
        raw_val = row.get("DATA_VALUE", "")
        if raw_val in ("", None):
            continue
        try:
            value = float(raw_val)
        except (TypeError, ValueError):
            continue
        times.append(ts)
        values.append(value)
    series = pd.Series(values, index=times, name=name)

    if as_of_date is not None:
        cutoff = _ecos_publication_cutoff(as_of_date, name)
        series = series[series.index.date <= cutoff]

    return series
