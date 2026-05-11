"""Dynamic event calendar — FOMC + BOK scraping + KR macro release rules.

Replaces previously hardcoded FOMC_DATES_2026 / BOK_DATES_2026 in news_macro.py.

- FOMC: scrapes federalreserve.gov fomccalendars page
- BOK:  scrapes bok.or.kr 통화정책방향 결정회의 listYear page
- KR macro releases (CPI/Employment/GDP): rule-based, follows KOSTAT standard schedule

All scrapes cached as JSON for 7 days under {data_cache_dir}/calendar/.
On fetch failure (network, parse error), returns empty list — calendar degrades
gracefully rather than crashing the pipeline.
"""
import calendar as _calendar
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.schemas.news import CalendarEvent

logger = logging.getLogger(__name__)

_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_BOK_URL_TEMPLATE = (
    "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do"
    "?mtgSe=A&menuNo=200755&searchYear={year}"
)
_CACHE_TTL_DAYS = 7
_HTTP_TIMEOUT_S = 10
_UA = "Mozilla/5.0 (TradingAgents/DB-GAPS)"

_MONTH_NAMES = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


def _cache_path(name: str) -> Path:
    base = Path(DEFAULT_CONFIG["data_cache_dir"]) / "calendar"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{name}.json"


def _read_cache(name: str) -> list[str] | None:
    p = _cache_path(name)
    if not p.exists():
        return None
    payload = json.loads(p.read_text(encoding="utf-8"))
    fetched_at = date.fromisoformat(payload["fetched_at"])
    if (date.today() - fetched_at).days > _CACHE_TTL_DAYS:
        return None
    return payload["dates"]


def _write_cache(name: str, iso_dates: list[str]) -> None:
    _cache_path(name).write_text(json.dumps({
        "fetched_at": date.today().isoformat(),
        "dates": iso_dates,
    }), encoding="utf-8")


def fetch_fomc_dates(years: Iterable[int]) -> list[date]:
    """Scrape Federal Reserve FOMC calendar.

    Each meeting is typically 2 days; we use the *second* (decision) day.
    """
    cache_key = f"fomc_{'_'.join(str(y) for y in sorted(years))}"
    cached = _read_cache(cache_key)
    if cached is not None:
        return [date.fromisoformat(d) for d in cached]

    try:
        r = requests.get(_FOMC_URL, headers={"User-Agent": _UA}, timeout=_HTTP_TIMEOUT_S)
        r.raise_for_status()
    except Exception as e:
        logger.warning("FOMC fetch failed: %s", e)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    dates: list[date] = []
    years_set = set(years)

    for panel in soup.find_all("div", class_=re.compile(r"panel-default")):
        heading = panel.find(class_=re.compile(r"panel-heading"))
        if not heading:
            continue
        m = re.search(r"(\d{4})\s+FOMC Meetings", heading.get_text())
        if not m:
            continue
        year = int(m.group(1))
        if year not in years_set:
            continue
        # Within each year panel: rows of month + day range
        for row in panel.find_all("div", class_=re.compile(r"row.*fomc")):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("div")]
            text = " ".join(cells)
            month_match = re.search(
                r"(January|February|March|April|May|June|July|August|September|October|November|December)",
                text,
            )
            day_match = re.search(r"(\d{1,2})[\-–](\d{1,2})", text)
            if not (month_match and day_match):
                continue
            month = _MONTH_NAMES[month_match.group(1)]
            decision_day = int(day_match.group(2))
            try:
                dates.append(date(year, month, decision_day))
            except ValueError:
                continue

    dates = sorted(set(dates))
    _write_cache(cache_key, [d.isoformat() for d in dates])
    return dates


def fetch_bok_dates(years: Iterable[int]) -> list[date]:
    """Scrape Bank of Korea 통화정책방향 결정회의 calendar.

    BOK page format per year: a table whose first column is '01월 15일(목)'.
    """
    all_dates: list[date] = []
    for year in years:
        cache_key = f"bok_{year}"
        cached = _read_cache(cache_key)
        if cached is not None:
            all_dates.extend(date.fromisoformat(d) for d in cached)
            continue

        url = _BOK_URL_TEMPLATE.format(year=year)
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=_HTTP_TIMEOUT_S)
            r.raise_for_status()
        except Exception as e:
            logger.warning("BOK fetch failed for %d: %s", year, e)
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        year_dates: list[date] = []
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if not cells:
                    continue
                m = re.match(r"\s*(\d{2})월\s*(\d{1,2})일", cells[0].get_text(strip=True))
                if not m:
                    continue
                try:
                    year_dates.append(date(year, int(m.group(1)), int(m.group(2))))
                except ValueError:
                    continue
            if year_dates:
                break  # First parseable table is the meeting table

        year_dates = sorted(set(year_dates))
        _write_cache(cache_key, [d.isoformat() for d in year_dates])
        all_dates.extend(year_dates)

    return sorted(set(all_dates))


# --- KR macro release schedule (rule-based) ---------------------------------
#
# KOSTAT publishes per a stable pattern. Encode the rules here rather than
# scraping kostat.go.kr (the domain has been moving to mods.go.kr without a
# clean public schedule API).

def _nth_business_day(year: int, month: int, n: int) -> date:
    """Return the nth business day of a year/month (Mon-Fri, KR holidays not excluded)."""
    count = 0
    for day in range(1, _calendar.monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
    return date(year, month, 1)


def kr_macro_release_calendar(as_of: date, days: int) -> list[CalendarEvent]:
    """Generate KR macro release events expected within [as_of, as_of + days].

    Patterns (per KOSTAT/BOK standard schedule):
      - CPI (소비자물가지수): 2nd business day of each month, prev-month data
      - Employment trends (고용동향): 2nd Wednesday of each month, prev-month data
      - Quarterly GDP (국민계정): 70 days after quarter end (approx, advance estimate)
    """
    end = as_of + timedelta(days=days)
    events: list[CalendarEvent] = []

    # Iterate by month over the window
    cursor = date(as_of.year, as_of.month, 1)
    while cursor <= end:
        y, m = cursor.year, cursor.month

        # CPI: 2nd business day
        cpi_date = _nth_business_day(y, m, 2)
        if as_of <= cpi_date <= end:
            events.append(CalendarEvent(
                event_date=cpi_date, region="KR", event_type="cpi",
                description="통계청 소비자물가지수 발표 (전월 데이터)",
                consensus=None,
            ))

        # Employment: 2nd Wednesday
        emp_date = _second_weekday(y, m, weekday=2)  # Wednesday=2
        if as_of <= emp_date <= end:
            events.append(CalendarEvent(
                event_date=emp_date, region="KR", event_type="employment",
                description="통계청 고용동향 발표 (전월 데이터)",
                consensus=None,
            ))

        # Quarterly GDP: 70 days after quarter end, advance estimate
        if m in (1, 4, 7, 10):  # quarter-end months (prev quarter ended)
            prev_q_end = date(y, m, 1) - timedelta(days=1)  # last day of prev month
            # Find the quarter-end (Mar/Jun/Sep/Dec) preceding cursor
            for qe_month in (12, 9, 6, 3):
                if qe_month < m or (qe_month == 12 and m == 1):
                    qy = y - 1 if qe_month == 12 and m == 1 else y
                    qe = date(qy, qe_month, _calendar.monthrange(qy, qe_month)[1])
                    gdp_date = qe + timedelta(days=70)
                    if as_of <= gdp_date <= end:
                        events.append(CalendarEvent(
                            event_date=gdp_date, region="KR", event_type="gdp",
                            description=f"한국은행 {qy}년 Q{(qe_month - 1) // 3 + 1} GDP 속보치 발표",
                            consensus=None,
                        ))
                    break

        # next month
        cursor = date(y + (m // 12), (m % 12) + 1, 1)

    return sorted(events, key=lambda e: e.event_date)


def _second_weekday(year: int, month: int, weekday: int) -> date:
    """Return the date of the 2nd given weekday (Mon=0..Sun=6) in a month."""
    first = date(year, month, 1)
    days_to_first = (weekday - first.weekday()) % 7
    second = first + timedelta(days=days_to_first + 7)
    return second
