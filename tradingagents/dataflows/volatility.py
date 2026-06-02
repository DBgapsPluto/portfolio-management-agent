from datetime import date

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series


VKOSPI_INDEX_CODE = "1037"  # KRX VKOSPI 지수 코드


def fetch_vix(start: date, end: date, api_key: str | None = None) -> pd.Series:
    """VIX from FRED (VIXCLS)."""
    return fetch_fred_series("vix_close", start, end, api_key=api_key)


def _raw_pykrx_index_call(code: str, start: date, end: date) -> pd.DataFrame:
    """Direct pykrx index call. Wrapped for mocking."""
    from pykrx import stock
    return stock.get_index_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)


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
    """VKOSPI close from KRX via pykrx. Empty Series on any failure.

    KNOWN LIMITATION (2026-05 audit, pykrx 1.2.8):
      KRX가 신규 API에서 VKOSPI 인덱스 코드 1037을 더 이상 ticker list에
      노출하지 않는다 (`stock.get_index_ticker_list(date)` 결과에 1037 없음).
      KRX 응답이 영문 컬럼(TRD_DD/CLSPRC_IDX/...)을 반환하지만 pykrx가
      한글 컬럼을 기대해서 `KeyError: '1037'` 발생. KRX_ID/PW가 있어도 동일.
      → graceful 빈 Series 반환. 호출자(market_risk_analyst)는 sentinel
      (staleness_days=99)로 떨어지며 systemic_score는 VIX/SKEW/VXN 등
      다른 변동성 신호로 보완.
      해결책: (1) pykrx 라이브러리 패치(외부) (2) KRX OpenAPI 직접 호출 모듈
      신규 작성 (3) yfinance에는 VKOSPI 등가 ticker 없음.

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
