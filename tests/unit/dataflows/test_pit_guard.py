from datetime import date

from tradingagents.dataflows.pit_guard import is_pit_stale, PIT_STALENESS_DAYS


def test_pit_staleness_threshold():
    today = date(2026, 6, 4)
    assert is_pit_stale(date(2026, 5, 15), today=today) is True    # 20일 전
    assert is_pit_stale(date(2026, 5, 27), today=today) is True    # 8일 전 (>7)
    assert is_pit_stale(date(2026, 5, 28), today=today) is False   # 7일 전 (==7, not >)
    assert is_pit_stale(date(2026, 5, 29), today=today) is False   # 6일 전
    assert is_pit_stale(today, today=today) is False               # 오늘


def test_pit_staleness_default_today():
    assert is_pit_stale(date(2000, 1, 1)) is True


def test_pit_staleness_constant():
    assert PIT_STALENESS_DAYS == 7
