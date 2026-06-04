"""pykrx ETF OHLCV 무한 hang 가드 (daemon-thread 하드 timeout).

pykrx/KRX 가 timeout 없이 socket read 에서 무한 정지 → technical analyst 의 유일
입력인 prices 가 freeze. 각 ticker 호출에 스레드-safe 하드 timeout 을 걸고, 실패
ticker 는 로그와 함께 skip 한다 (silent 누락 방지).
"""
import time
from datetime import date

import pytest

from tradingagents.dataflows import pykrx_data as pk


def test_run_with_timeout_aborts_hang():
    """무한 hang 하는 호출을 timeout 으로 강제 중단 (TimeoutError)."""
    with pytest.raises(TimeoutError):
        pk._run_with_timeout(lambda: time.sleep(5), timeout=0.3)


def test_run_with_timeout_returns_value():
    """정상 호출은 값을 그대로 반환."""
    assert pk._run_with_timeout(lambda: 42, timeout=1.0) == 42


def test_run_with_timeout_propagates_exception():
    """내부 예외는 그대로 전파 (timeout 아닌 실패)."""
    def boom():
        raise ValueError("inner")
    with pytest.raises(ValueError):
        pk._run_with_timeout(boom, timeout=1.0)


def test_fetch_etf_ohlcv_graceful_on_timeout(monkeypatch):
    """ticker 호출이 hang 하면 빈 df 로 graceful skip (node freeze 방지)."""
    monkeypatch.setattr(pk, "_PYKRX_CALL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(pk, "_raw_pykrx_call", lambda t, s, e: time.sleep(5))

    df = pk.fetch_etf_ohlcv("A069500", date(2026, 1, 1), date(2026, 1, 2))

    assert df.empty
