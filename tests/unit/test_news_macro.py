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
