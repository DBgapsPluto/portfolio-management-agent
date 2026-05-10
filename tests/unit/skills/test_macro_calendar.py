from datetime import date
from tradingagents.skills.macro.calendar import fetch_central_bank_calendar_skill


def test_calendar_window():
    events = fetch_central_bank_calendar_skill(date(2026, 5, 10), days=90)
    assert all(e.event_date >= date(2026, 5, 10) for e in events)
    assert all(e.event_type == "rate_decision" for e in events)
