from datetime import date

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series


def fetch_vix(start: date, end: date, api_key: str | None = None) -> pd.Series:
    """VIX from FRED (VIXCLS)."""
    return fetch_fred_series("vix_close", start, end, api_key=api_key)


def _live_vkospi(start: date, end: date) -> pd.Series:
    """VKOSPI 종가 시계열 — KRX 공식 OpenAPI (idx/drvprod_dd_trd).

    pykrx get_index_ohlcv(1037)이 KRX schema 변경(영문 컬럼)으로 깨져 공식 API
    로 이전 (2026-06-03). 공식 API는 단일일자라 날짜별 루프 (series_cache 가
    as_of 별 1회만 수행).
    """
    try:
        from tradingagents.dataflows.krx_openapi import fetch_index_series
        data = fetch_index_series(start, end, "코스피 200 변동성지수", "drvprod")
        if not data:
            return pd.Series(dtype=float, name="VKOSPI")
        idx = pd.to_datetime(list(data.keys()), format="%Y%m%d")
        return pd.Series(list(data.values()), index=idx, name="VKOSPI").sort_index()
    except Exception:
        return pd.Series(dtype=float, name="VKOSPI")


def fetch_vkospi(
    start: date, end: date,
    use_cache: bool = True,
    max_staleness: int = 7,
) -> pd.Series:
    """VKOSPI close from the KRX official OpenAPI (drvprod / "코스피 200 변동성지수").

    Source migrated 2026-06-03 from pykrx get_index_ohlcv(1037) — which KRX broke
    by dropping index 1037 from the new API — to a direct KRX OpenAPI call
    (`_live_vkospi` → `krx_openapi.fetch_index_series`). VERIFIED working live with
    KRX credentials (2026-06-15). Returns an empty Series on any failure; the
    caller (market_risk_analyst) then falls back to a sentinel (staleness_days=99)
    which is rendered as 'n/a' so a fetch failure is never read as a calm 0.0.

    Requires KRX_API_KEY (or KRX_ID/KRX_PW) in the environment.
    Cache: ~/.tradingagents/cache/pykrx_index/vkospi/{end}.json
    """
    if not use_cache:
        return _live_vkospi(start, end)

    from tradingagents.dataflows.series_cache import fetch_series_with_cache
    try:
        return fetch_series_with_cache(
            lambda: _live_vkospi(start, end),
            namespace="pykrx_index",
            cache_key="vkospi",
            as_of=end,
            max_staleness=max_staleness,
        )
    except Exception:
        return pd.Series(dtype=float, name="VKOSPI")
