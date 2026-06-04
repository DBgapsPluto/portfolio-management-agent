"""KOFIA FreeSIS 신용공여 통계 직접 호출 wrapper.

배경:
  시장 전체 신용거래융자 잔고(=신용잔고)는 KRX 공식 OpenAPI / KRX 정보데이터시스템 /
  한국은행 ECOS 어디에도 없고(2026-06-04 실증), 금융투자협회 FreeSIS 만 제공한다.
  FreeSIS는 eXBuilder6 SPA 지만 데이터 grid 는 /meta/getMetaDataList.do (JSON POST)
  로 받아오며, 쿠키/인증 없이 plain requests 로 호출된다 (브라우저 XHR 캡처로
  endpoint·body·schema 확정).

serviceId STATSCU0100000070 = 신용공여 잔고 추이. 응답 ds1[]:
  TMPV1=날짜(YYYYMMDD), TMPV2=신용거래융자 전체(백만원),
  TMPV3/4=융자 유가증권/코스닥, TMPV5~7=신용거래대주, TMPV9=예탁증권담보융자.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import requests
from tenacity import (
    retry, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

logger = logging.getLogger(__name__)

_URL = "https://freesis.kofia.or.kr/meta/getMetaDataList.do"
_TIMEOUT_SEC = 30
_CREDIT_LOAN_SERVICE = "STATSCU0100000070BO"  # 신용공여 잔고 추이
_MILLION = 1_000_000  # 응답 단위(백만원) → 원


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.ConnectionError, requests.Timeout)),
)
def _raw_credit_loan_call(start: date, end: date) -> list[dict]:
    """FreeSIS getMetaDataList.do 호출 → ds1 record list. 빈 응답 시 빈 list."""
    body = {
        "dmSearch": {
            "tmpV40": "1000000",   # 단위(백만원)
            "tmpV41": "1",
            "tmpV1": "D",           # 자료주기 = 일별
            "tmpV45": start.strftime("%Y%m%d"),
            "tmpV46": end.strftime("%Y%m%d"),
            "OBJ_NM": _CREDIT_LOAN_SERVICE,
        }
    }
    r = requests.post(_URL, json=body, timeout=_TIMEOUT_SEC)
    r.raise_for_status()
    return r.json().get("ds1", []) or []


def fetch_credit_loan_balance(start: date, end: date) -> pd.Series:
    """KOFIA 신용거래융자 잔고(전체, TMPV2) 시계열 (KRW).

    index=date(시간 오름차순), value=원. 빈/실패 시 빈 Series
    (name='credit_balance') → kr_margin sentinel graceful.
    """
    try:
        rows = _raw_credit_loan_call(start, end)
    except Exception as e:
        logger.warning("KOFIA credit loan balance fetch failed: %s", e)
        return pd.Series(dtype=float, name="credit_balance")

    recs: list[tuple[pd.Timestamp, float]] = []
    for r in rows:
        d, v = r.get("TMPV1"), r.get("TMPV2")
        if d is None or v is None:
            continue
        try:
            recs.append((pd.Timestamp(str(d)), float(v) * _MILLION))
        except (ValueError, TypeError):
            continue
    if not recs:
        return pd.Series(dtype=float, name="credit_balance")

    recs.sort(key=lambda x: x[0])  # 시간 오름차순 (iloc[-1]=최신)
    return pd.Series(
        [v for _, v in recs], index=[d for d, _ in recs], name="credit_balance",
    )
