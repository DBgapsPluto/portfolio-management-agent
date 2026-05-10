from datetime import date
from tradingagents.skills.news.event_calendar import fetch_event_calendar_skill


def test_event_calendar_returns_list():
    events = fetch_event_calendar_skill(date(2026, 5, 10), days=90)
    assert isinstance(events, list)
