import logging
from datetime import date, datetime, timedelta
from time import mktime

import feedparser

from tradingagents.schemas.news import CalendarEvent, NewsItem

logger = logging.getLogger(__name__)


# 2026 FOMC + BOK 일정 (수동 시드)
FOMC_DATES_2026 = [
    date(2026, 5, 14), date(2026, 6, 18), date(2026, 7, 30),
    date(2026, 9, 17), date(2026, 11, 5), date(2026, 12, 17),
]
BOK_DATES_2026 = [
    date(2026, 5, 22), date(2026, 7, 10), date(2026, 8, 28),
    date(2026, 10, 16), date(2026, 11, 27),
]


def fetch_macro_news(rss_urls: list[str], window_days: int = 7) -> list[NewsItem]:
    """Pull headlines from RSS sources. No body fetched (intentional — D2 schema lock)."""
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    items: list[NewsItem] = []
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logger.warning("RSS fetch failed for %s: %s", url, e)
            continue
        for entry in feed.entries[:50]:
            try:
                published = datetime.fromtimestamp(mktime(entry["published_parsed"]))
                if published < cutoff:
                    continue
                items.append(NewsItem(
                    headline=entry["title"][:300],
                    source=feed.feed.get("title", url) if hasattr(feed, "feed") else url,
                    published_at=published,
                    url=entry.get("link", ""),
                ))
            except (KeyError, TypeError):
                continue
    return items


def fetch_calendar_events(as_of: date, days: int = 30) -> list[CalendarEvent]:
    """Return FOMC/BOK events within window."""
    end = as_of + timedelta(days=days)
    events: list[CalendarEvent] = []
    for d in FOMC_DATES_2026:
        if as_of <= d <= end:
            events.append(CalendarEvent(
                event_date=d, region="US", event_type="fomc",
                description="FOMC rate decision", consensus=None,
            ))
    for d in BOK_DATES_2026:
        if as_of <= d <= end:
            events.append(CalendarEvent(
                event_date=d, region="KR", event_type="bok",
                description="한국은행 통화정책방향 결정회의", consensus=None,
            ))
    return sorted(events, key=lambda e: e.event_date)
