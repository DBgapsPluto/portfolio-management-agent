from datetime import date, datetime
from unittest.mock import patch

from tradingagents.dataflows.news_macro import (
    fetch_macro_news, fetch_calendar_events,
)
from tradingagents.schemas.news import NewsItem, CalendarEvent


def test_fetch_news_returns_items():
    fake_feed = type("F", (), {})()
    fake_feed.entries = [
        {
            "title": "Fed signals 25bp cut",
            "link": "https://example.com/x",
            "published_parsed": (2026, 5, 10, 14, 30, 0, 0, 0, 0),
        },
    ]
    fake_feed.feed = type("FD", (), {})()
    fake_feed.feed.get = lambda key, default=None: "Test Feed"
    with patch("feedparser.parse", return_value=fake_feed):
        items = fetch_macro_news(["https://reuters.example/rss"], window_days=10000)
    assert len(items) == 1
    assert isinstance(items[0], NewsItem)
    assert items[0].headline.startswith("Fed")


def test_fetch_calendar_minimal():
    events = fetch_calendar_events(date(2026, 5, 10), days=30)
    assert all(isinstance(e, CalendarEvent) for e in events)


# ---- 2026-05-28 Tier 1: RSS description extraction ----


def test_extract_rss_description_from_summary():
    """feedparser entry 의 summary field → NewsItem.description."""
    from tradingagents.dataflows.news_macro import _extract_rss_description
    entry = {"summary": "This is a meaningful summary of the news article with enough content."}
    result = _extract_rss_description(entry)
    assert result is not None
    assert "meaningful summary" in result


def test_extract_rss_description_strips_html():
    """HTML tag 제거."""
    from tradingagents.dataflows.news_macro import _extract_rss_description
    entry = {"summary": "<p>This is <b>bold</b> text inside HTML tags for testing.</p>"}
    result = _extract_rss_description(entry)
    assert "<p>" not in result
    assert "<b>" not in result
    assert "bold" in result


def test_extract_rss_description_too_short_returns_none():
    """20자 미만 = headline 중복 가능 → None."""
    from tradingagents.dataflows.news_macro import _extract_rss_description
    assert _extract_rss_description({"summary": "short"}) is None
    assert _extract_rss_description({}) is None
    assert _extract_rss_description({"summary": ""}) is None


def test_fetch_macro_news_populates_description():
    """fetch_macro_news 가 RSS description 도 추출."""
    from datetime import datetime
    from time import mktime
    pt = datetime.now().timetuple()
    fake_feed = type("F", (), {
        "entries": [{
            "title": "Fed signals 25bp cut",
            "summary": "Federal Reserve officials hinted at a possible rate cut next quarter citing easing inflation.",
            "published_parsed": pt,
            "link": "https://example.com/news/1",
        }],
        "feed": {"title": "Reuters"},
    })()
    with patch("feedparser.parse", return_value=fake_feed):
        items = fetch_macro_news(["https://reuters.example/rss"], window_days=10000)
    assert len(items) == 1
    assert items[0].description is not None
    assert "Federal Reserve" in items[0].description
