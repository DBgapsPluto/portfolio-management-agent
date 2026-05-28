import logging
from datetime import date, datetime, timedelta
from time import mktime

import feedparser

from tradingagents.schemas.news import CalendarEvent, NewsItem

logger = logging.getLogger(__name__)


from tradingagents.dataflows.event_calendar_fetcher import (
    fetch_bok_dates,
    fetch_fomc_dates,
    kr_macro_release_calendar,
)


def _extract_rss_description(entry) -> str | None:
    """RSS entry 의 description/summary field 추출 (Tier 1).

    Source 별 field 이름 다양 (description / summary / content / subtitle).
    HTML tag 제거 후 ≤2000자 truncate. 빈 string 은 None 반환.
    """
    import re

    raw = (
        entry.get("summary")
        or entry.get("description")
        or (entry.get("content", [{}])[0].get("value") if entry.get("content") else None)
        or entry.get("subtitle")
    )
    if not raw or not isinstance(raw, str):
        return None
    # HTML tag 제거 (간단한 stripping — bleach/lxml 없이)
    cleaned = re.sub(r"<[^>]+>", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # CDATA, entity 제거
    cleaned = cleaned.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    # headline 과 동일한 경우 None (중복)
    if len(cleaned) < 20:
        return None
    return cleaned[:2000]


def fetch_macro_news(rss_urls: list[str], window_days: int = 7) -> list[NewsItem]:
    """Pull headlines from RSS sources.

    2026-05-28: Tier 1 — RSS description/summary 도 추출 (NewsItem.description).
    추가 HTTP 호출 없이 headline 보다 풍부한 context 제공. Tier 2 (body fetch)
    는 별도 module (news_body_fetcher.py) 에서.
    """
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
                description = _extract_rss_description(entry)
                items.append(NewsItem(
                    headline=entry["title"][:300],
                    source=feed.feed.get("title", url) if hasattr(feed, "feed") else url,
                    published_at=published,
                    url=entry.get("link", ""),
                    description=description,
                ))
            except (KeyError, TypeError):
                continue
    return items


def fetch_calendar_events(as_of: date, days: int = 30) -> list[CalendarEvent]:
    """Return FOMC + BOK + KR macro release events within [as_of, as_of+days].

    FOMC and BOK dates are fetched live from federalreserve.gov and bok.or.kr
    (7-day file cache). KR macro releases (CPI/Employment/GDP) are generated
    from KOSTAT's standard monthly/quarterly schedule.
    """
    end = as_of + timedelta(days=days)
    years = sorted({as_of.year, end.year})
    events: list[CalendarEvent] = []

    for d in fetch_fomc_dates(years):
        if as_of <= d <= end:
            events.append(CalendarEvent(
                event_date=d, region="US", event_type="fomc",
                description="FOMC rate decision", consensus=None,
            ))
    for d in fetch_bok_dates(years):
        if as_of <= d <= end:
            events.append(CalendarEvent(
                event_date=d, region="KR", event_type="bok",
                description="한국은행 통화정책방향 결정회의", consensus=None,
            ))
    events.extend(kr_macro_release_calendar(as_of, days))

    return sorted(events, key=lambda e: e.event_date)
