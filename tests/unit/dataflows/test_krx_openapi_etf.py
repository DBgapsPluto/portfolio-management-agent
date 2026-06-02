"""KRX OpenAPI ETF endpoint wrapper tests."""
from datetime import date

import pytest

from tradingagents.dataflows.krx_openapi import fetch_etf_daily_detail


def _fake_records():
    """Mock KRX OpenAPI response — 2 ETF records."""
    return [
        {
            "ISU_CD": "069500", "BAS_DD": "20260528",
            "NAV": "45123.45", "TDD_CLSPRC": "45130",
            "ACC_TRDVOL": "1234567", "ACC_TRDVAL": "55600000000",
            "MKTCAP": "16480300000000",
            "TRC_RT": "99.85",
        },
        {
            "ISU_CD": "360750", "BAS_DD": "20260528",
            "NAV": "18250.10", "TDD_CLSPRC": "18260",
            "ACC_TRDVOL": "5432100", "ACC_TRDVAL": "99100000000",
            "MKTCAP": "14782100000000",
            "TRC_RT": "99.92",
        },
    ]


def test_fetch_etf_daily_detail_returns_all_when_ticker_none(monkeypatch):
    """ticker=None 시 전체 ETF 응답 반환."""
    monkeypatch.setattr(
        "tradingagents.dataflows.krx_openapi.fetch_krx_openapi",
        lambda endpoint, basDd: _fake_records(),
    )
    records = fetch_etf_daily_detail(date(2026, 5, 28))
    assert len(records) == 2
    assert records[0]["ISU_CD"] == "069500"


def test_fetch_etf_daily_detail_filters_by_ticker(monkeypatch):
    """ticker 지정 시 단일 record."""
    monkeypatch.setattr(
        "tradingagents.dataflows.krx_openapi.fetch_krx_openapi",
        lambda endpoint, basDd: _fake_records(),
    )
    records = fetch_etf_daily_detail(date(2026, 5, 28), ticker="069500")
    assert len(records) == 1
    assert records[0]["ISU_CD"] == "069500"


def test_fetch_etf_daily_detail_returns_empty_when_ticker_not_found(monkeypatch):
    """존재하지 않는 ticker → 빈 list."""
    monkeypatch.setattr(
        "tradingagents.dataflows.krx_openapi.fetch_krx_openapi",
        lambda endpoint, basDd: _fake_records(),
    )
    records = fetch_etf_daily_detail(date(2026, 5, 28), ticker="999999")
    assert records == []


def test_fetch_etf_daily_detail_empty_response(monkeypatch):
    """KRX 가 빈 응답 시 (공휴일) 빈 list 반환."""
    monkeypatch.setattr(
        "tradingagents.dataflows.krx_openapi.fetch_krx_openapi",
        lambda endpoint, basDd: [],
    )
    records = fetch_etf_daily_detail(date(2026, 5, 24))  # Sunday
    assert records == []
