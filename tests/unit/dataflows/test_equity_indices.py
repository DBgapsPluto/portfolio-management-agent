"""equity_indices ticker 맵 검증 — delisted ticker 회귀 방지.

usdcnh 의 yfinance ticker 'CNH=X' (및 'USDCNH=X') 가 2026 시점 delisted →
china_leading 에 usdcnh=0.0 (무의미값)이 silent 주입됐다. 작동 ticker로 교체.
"""
from datetime import date, timedelta

import pytest

from tradingagents.dataflows.equity_indices import (
    EQUITY_INDEX_TICKERS, fetch_equity_index_close,
)


def test_usdcnh_ticker_is_not_delisted_cnh():
    """usdcnh ticker 는 delisted 된 CNH=X / USDCNH=X 가 아니어야 한다."""
    assert EQUITY_INDEX_TICKERS["usdcnh"] not in ("CNH=X", "USDCNH=X")


@pytest.mark.slow
def test_usdcnh_ticker_returns_live_data():
    """usdcnh ticker 가 실제 환율 데이터를 반환해야 (네트워크)."""
    as_of = date(2026, 6, 2)
    s = fetch_equity_index_close("usdcnh", as_of - timedelta(days=40), as_of)
    assert s is not None and len(s) > 0
    assert float(s.iloc[-1]) > 0
