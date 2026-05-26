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
