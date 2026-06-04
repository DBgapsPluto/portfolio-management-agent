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


from tradingagents.dataflows.news_macro import fetch_macro_news
from tradingagents.skills.news.news_fetcher import fetch_macro_news_skill
from tradingagents.skills.risk.fear_greed import fetch_fear_greed_index


def test_news_suppressed_when_stale():
    # 먼 과거 as_of → 빈 리스트 (네트워크/feedparser 미호출)
    assert fetch_macro_news(["http://example.com/rss"], as_of=date(2000, 1, 1)) == []
    assert fetch_macro_news_skill(as_of=date(2000, 1, 1)) == []


def test_fear_greed_suppressed_when_stale():
    # 먼 과거 as_of → None (scrape/cache 미접근)
    assert fetch_fear_greed_index(date(2000, 1, 1)) is None
