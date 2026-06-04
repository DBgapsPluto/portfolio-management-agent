"""KOFIA FreeSIS 신용거래융자 잔고 fetch 검증.

소스: freesis.kofia.or.kr/meta/getMetaDataList.do (serviceId STATSCU0100000070,
신용공여 잔고 추이). 응답 ds1[].TMPV1=날짜(YYYYMMDD), TMPV2=신용거래융자 전체(백만원).
실제 브라우저 XHR 캡처(2026-06-04)로 endpoint·body·schema 확정.
"""
from datetime import date

import pandas as pd
import pytest

from tradingagents.dataflows import kofia_freesis

# 실제 캡처 응답(2026-06-04) 축약 — 최신이 먼저(내림차순)로 온다.
_CAPTURED = {
    "unit": "",
    "ds1": [
        {"TMPV1": "20260602", "TMPV2": 37709128, "TMPV3": 27924185, "TMPV4": 9784943},
        {"TMPV1": "20260601", "TMPV2": 37681169, "TMPV3": 27845647, "TMPV4": 9835522},
        {"TMPV1": "20260529", "TMPV2": 38022681, "TMPV3": 28024472, "TMPV4": 9998209},
    ],
}


class _FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_fetch_credit_loan_balance_parses_tmpv2_ascending_in_krw(monkeypatch):
    """TMPV2(신용거래융자 전체, 백만원) → 시간 오름차순 pd.Series, 원 단위."""
    monkeypatch.setattr(
        kofia_freesis.requests, "post", lambda *a, **k: _FakeResp(_CAPTURED)
    )

    s = kofia_freesis.fetch_credit_loan_balance(date(2026, 5, 29), date(2026, 6, 2))

    assert isinstance(s, pd.Series)
    assert s.name == "credit_balance"
    # 시간 오름차순 (compute_kr_margin_debt 가 iloc[-1]=최신 가정)
    assert list(pd.to_datetime(s.index).strftime("%Y%m%d")) == [
        "20260529", "20260601", "20260602",
    ]
    # 백만원 → 원 변환
    assert s.iloc[-1] == 37709128 * 1_000_000
    assert s.iloc[0] == 38022681 * 1_000_000


def test_fetch_credit_loan_balance_empty_on_no_rows(monkeypatch):
    """ds1 없음/빈 응답 → 빈 Series (graceful sentinel)."""
    monkeypatch.setattr(
        kofia_freesis.requests, "post", lambda *a, **k: _FakeResp({"ds1": []})
    )

    s = kofia_freesis.fetch_credit_loan_balance(date(2026, 6, 1), date(2026, 6, 2))

    assert isinstance(s, pd.Series)
    assert s.empty


@pytest.mark.slow
def test_fetch_credit_loan_balance_live():
    """실제 KOFIA 호출 — 최근 신용융자 잔고가 양수로 온다 (네트워크 필요)."""
    s = kofia_freesis.fetch_credit_loan_balance(date(2026, 3, 2), date(2026, 6, 2))
    assert not s.empty
    assert s.iloc[-1] > 0
