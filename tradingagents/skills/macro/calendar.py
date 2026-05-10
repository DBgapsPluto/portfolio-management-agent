from datetime import date

from tradingagents.dataflows.news_macro import fetch_calendar_events
from tradingagents.schemas.macro import CentralBankEvent
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_central_bank_calendar", category="macro")
def fetch_central_bank_calendar_skill(as_of: date, days: int = 90) -> list[CentralBankEvent]:
    """Wrap dataflows fetch_calendar_events; convert FOMC/BOK to CentralBankEvent."""
    raw = fetch_calendar_events(as_of, days)
    out = []
    for e in raw:
        if e.event_type in ("fomc", "bok"):
            out.append(CentralBankEvent(
                bank="FED" if e.event_type == "fomc" else "BOK",
                event_date=e.event_date,
                event_type="rate_decision",
                description=e.description,
            ))
    return out
