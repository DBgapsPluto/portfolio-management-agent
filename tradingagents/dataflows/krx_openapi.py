"""KRX OpenAPI 직접 호출 wrapper.

배경:
  pykrx 라이브러리가 KRX 신규 API schema 변경 (영문 컬럼 TRD_DD/CLSPRC_IDX/...)
  으로 일부 endpoint 깨짐 — get_etf_isin, get_index_portfolio_deposit_file,
  VKOSPI(1037) 등. KRX 가 공식 OpenAPI (https://data-dbg.krx.co.kr/svc/apis/)
  를 제공하므로 그것을 직접 호출.

인증: HTTP header AUTH_KEY 에 KRX_API_KEY 환경변수 값 전달.

응답: 모든 endpoint 가 JSON `{"OutBlock_1": [...records]}` 형태.

본 모듈은 단순 wrapper — 특정 endpoint 의 schema 해석은 caller 책임.
"""
from __future__ import annotations

import logging
import os
from datetime import date

import requests
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
_TIMEOUT_SEC = 30


class KRXOpenAPIError(RuntimeError):
    """KRX OpenAPI 호출 실패 (network / HTTP / schema)."""


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
)
def fetch_krx_openapi(endpoint_path: str, basDd: str | date) -> list[dict]:
    """KRX OpenAPI endpoint 호출 → OutBlock_1 list 반환.

    Args:
        endpoint_path: "sto/stk_isu_base_info" 등 (base url 뒤 path).
        basDd: 기준일자 — date 객체 또는 YYYYMMDD 문자열.

    Returns:
        list of records (dict). 빈 결과 시 빈 list.

    Raises:
        KRXOpenAPIError: 인증 실패, HTTP error, malformed response.
    """
    api_key = os.environ.get("KRX_API_KEY")
    if not api_key:
        raise KRXOpenAPIError("KRX_API_KEY 환경 변수 미설정")

    if isinstance(basDd, date):
        basDd = basDd.strftime("%Y%m%d")

    url = f"{_BASE_URL}/{endpoint_path}"
    headers = {"AUTH_KEY": api_key}
    params = {"basDd": basDd}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=_TIMEOUT_SEC)
    except (requests.ConnectionError, requests.Timeout):
        raise
    except requests.RequestException as e:
        raise KRXOpenAPIError(f"KRX request failed: {e}") from e

    if r.status_code != 200:
        raise KRXOpenAPIError(
            f"KRX HTTP {r.status_code}: {r.text[:200]}"
        )

    try:
        payload = r.json()
    except ValueError as e:
        raise KRXOpenAPIError(f"KRX response not JSON: {e}") from e

    records = payload.get("OutBlock_1", [])
    if not isinstance(records, list):
        raise KRXOpenAPIError(
            f"KRX response OutBlock_1 not a list: {type(records).__name__}"
        )

    logger.debug(
        "KRX %s basDd=%s → %d records", endpoint_path, basDd, len(records),
    )
    return records


# KRX 공식 OpenAPI 카탈로그에서 live 검증된 endpoint (2026-06-03).
# ETF 는 'etp' (증권상품) 카테고리 — 'etf/etf_bydd_trd' 는 404 (존재 안 함).
KRX_ETF_DAILY_ENDPOINT: str = "etp/etf_bydd_trd"
# 지수 일별: idx/{series}_dd_trd. series=kospi 응답에 KOSPI200,
# series=drvprod 응답에 '코스피 200 변동성지수'(VKOSPI) 포함.
KRX_INDEX_KOSPI_ENDPOINT: str = "idx/kospi_dd_trd"
KRX_INDEX_DRVPROD_ENDPOINT: str = "idx/drvprod_dd_trd"


def fetch_etf_daily_detail(
    basDd: date,
    ticker: str | None = None,
) -> list[dict]:
    """ETF 일별 상세 (종가/OHLCV, NAV, 거래량, AUM).

    Args:
        basDd: 기준일자 (영업일).
        ticker: 단축코드 6자리 (예: "069500"). None 시 전 ETF 응답.

    Returns:
        list of records (dict). 빈 응답(휴장일 등) 시 빈 list.
        주요 필드: ISU_CD, ISU_NM, BAS_DD, TDD_CLSPRC(종가),
                  TDD_OPNPRC/HGPRC/LWPRC, NAV, ACC_TRDVOL, ACC_TRDVAL, MKTCAP.
    """
    records = fetch_krx_openapi(KRX_ETF_DAILY_ENDPOINT, basDd)
    if ticker is None:
        return records
    return [r for r in records if r.get("ISU_CD") == ticker]


def _to_float(v) -> float | None:
    """KRX 응답 문자열("141395", "1,399.91") → float. 실패 시 None."""
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def fetch_etf_close_map(basDd: date) -> dict[str, float]:
    """전 ETF 종가 맵 {f"A{단축코드}": 종가}. 휴장일/실패 시 빈 dict.

    universe.json / weight_vector 의 ticker 가 'A' prefix 형식이므로 맞춰 반환.
    """
    out: dict[str, float] = {}
    for r in fetch_etf_daily_detail(basDd):
        code = r.get("ISU_CD")
        close = _to_float(r.get("TDD_CLSPRC"))
        if code and close is not None and close > 0:
            out[f"A{code}"] = close
    return out


def fetch_index_close(
    basDd: date, idx_name: str, series: str = "kospi",
) -> float | None:
    """지수 종가 (IDX_NM 정확 일치). series: 'kospi' | 'drvprod' 등.

    예: fetch_index_close(d, "코스피 200")          → KOSPI200 종가
        fetch_index_close(d, "코스피 200 변동성지수", "drvprod") → VKOSPI
    """
    endpoint = f"idx/{series}_dd_trd"
    for r in fetch_krx_openapi(endpoint, basDd):
        if str(r.get("IDX_NM", "")).strip() == idx_name:
            return _to_float(r.get("CLSPRC_IDX"))
    return None
