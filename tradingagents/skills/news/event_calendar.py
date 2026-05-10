from datetime import date

from tradingagents.dataflows.news_macro import fetch_calendar_events
from tradingagents.schemas.news import CalendarEvent
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_event_calendar", category="news")
def fetch_event_calendar_skill(as_of: date, days: int = 90) -> list[CalendarEvent]:
    return fetch_calendar_events(as_of, days)
