"""Tier-5 — SAVE 브리핑 ingestor (축소형).

추출 대상 (다른 분석가가 안 잡는 것만):
  1. 경제지표 발표 (★ 중요도 + 예상/실제) → Tier-2 ReleaseSurprise 채움
  2. 뉴스 카드 (큐레이션된 한/영 헤드라인) → Tier-3 input 보강
  3. 주간 일정 (국채 경매·예정 지표) → event_calendar 보강

가격 수치는 skip — Tier-1 global_overnight + macro_quant + market_risk 중복.
"""
import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from tradingagents.dataflows.save_brief import (
    find_latest_save_brief, load_save_brief_text,
    parse_brief_date, split_save_brief_pages,
)
from tradingagents.schemas.news import (
    CalendarEvent, NewsItem, ReleaseSurprise, SaveBriefSnapshot,
)
from tradingagents.skills.news.release_surprise import normalize_release
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


# 경제지표 한 줄 패턴 (KST 시간 + region + indicator + ★ + 실제값 + (예상: ... 이전: ...))
RELEASE_LINE_RE = re.compile(
    r"(?P<time>\d{2}:\d{2})\s*[-–]\s*"
    r"(?P<region>[가-힣A-Za-z][가-힣A-Za-z\s]+?)\s*[-–]\s*"
    r"(?P<indicator>[^★\n]+?)\s*"
    r"(?P<stars>★+)\s*"
    r"(?P<actual>[\+\-\d.,KMB%]+)?\s*"
    r"[▲▼=]?\s*"
    r"\(예상\s*[:：]?\s*(?P<forecast>[\+\-\d.,KMB%]+)?\s*"
    r"(?:[\s,]+이전\s*[:：]?\s*(?P<previous>[\+\-\d.,KMB%]+)?)?\s*\)?",
    re.MULTILINE,
)


REGION_MAP = {
    "미국": "US", "한국": "KR", "일본": "JP", "중국": "CN",
    "유럽": "EU", "독일": "EU", "프랑스": "EU", "영국": "UK",
    "연준": "US", "fed": "US", "ecb": "EU", "boj": "JP", "bok": "KR",
}


def _to_region(raw: str):
    lower = raw.strip().lower()
    for k, v in REGION_MAP.items():
        if k in lower:
            return v
    return "GLOBAL"


def _parse_value(raw: str | None) -> tuple[float | None, str]:
    """Return (value, unit). unit ∈ {pct, k, m, bps, level}."""
    if raw is None:
        return None, "level"
    s = raw.strip().replace(",", "").replace("+", "")
    unit = "level"
    if "%" in s:
        unit = "pct"
        s = s.replace("%", "")
    elif s.upper().endswith("K"):
        unit = "k"
        s = s[:-1]
    elif s.upper().endswith("M"):
        unit = "m"
        s = s[:-1]
    try:
        return float(s), unit
    except ValueError:
        return None, unit


def parse_economic_releases(
    pages: list[str], brief_date: date,
) -> list[ReleaseSurprise]:
    """[경제 지표] 섹션이 있는 페이지에서 발표 list 추출."""
    out: list[ReleaseSurprise] = []
    for page in pages:
        if "[경제 지표]" not in page and "경제지표" not in page:
            continue
        for m in RELEASE_LINE_RE.finditer(page):
            region = _to_region(m.group("region") or "")
            indicator = (m.group("indicator") or "").strip()
            stars = m.group("stars") or ""
            importance = min(3, max(1, len(stars)))
            actual_raw = m.group("actual")
            forecast_raw = m.group("forecast")
            previous_raw = m.group("previous")
            actual, unit = _parse_value(actual_raw)
            forecast, _ = _parse_value(forecast_raw)
            previous, _ = _parse_value(previous_raw)
            if actual is None and forecast is None:
                continue
            raw_rel = ReleaseSurprise(
                release_date=brief_date, region=region, indicator=indicator,
                importance=importance,
                forecast=forecast, actual=actual, previous=previous,
                surprise=None, surprise_zscore=None, direction="unknown",
                unit=unit,  # type: ignore[arg-type]
            )
            out.append(normalize_release(raw_rel, historical_std=None))
    return out


_NEWS_CARD_HEADER_RE = re.compile(r"오늘의\s*소식|전일\s*요약")
_EN_TITLE_RE = re.compile(r"^[A-Z][A-Za-z'’&\-\s\d,:%]+[A-Za-z\d.?!]$")


def parse_news_cards_heuristic(pages: list[str]) -> list[NewsItem]:
    """간단 휴리스틱 — 영문 원제가 있는 페이지에서 한글 첫 줄을 title로 채집.

    LLM 없이도 동작. LLM 활용 옵션은 parse_news_cards_with_llm 별도 함수.
    """
    out: list[NewsItem] = []
    now = datetime.now()
    for page in pages:
        if not _NEWS_CARD_HEADER_RE.search(page):
            continue
        # 페이지 내 영문 1줄이 있고, 그 직전 한글 1줄이 있는 패턴
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        for i, ln in enumerate(lines):
            if _EN_TITLE_RE.match(ln) and len(ln) >= 20:
                # 직전 한글 줄 찾기
                kr_title = None
                for back in range(i - 1, max(-1, i - 5), -1):
                    candidate = lines[back]
                    if re.search(r"[가-힣]", candidate) and len(candidate) >= 4:
                        kr_title = candidate
                        break
                if kr_title:
                    headline = f"{kr_title} — {ln}"[:300]
                    out.append(NewsItem(
                        headline=headline, source="SAVE",
                        published_at=now, url="local://save_brief",
                    ))
                    break
    return out


def parse_news_cards_with_llm(
    pages: list[str], brief_date: date, quick_llm,
) -> list[NewsItem]:
    """LLM batch 추출 — 정확도 ↑. quick_llm 없으면 [] 반환."""
    if quick_llm is None:
        return []
    candidate_pages = [p for p in pages if _NEWS_CARD_HEADER_RE.search(p)]
    if not candidate_pages:
        return []
    joined = "\n\n=== PAGE BREAK ===\n\n".join(candidate_pages[:20])
    prompt = (
        "Below is text extracted from a Korean daily market briefing. "
        "Extract news headlines as JSON array.\n"
        "Each entry: {\"title_kr\": \"...\", \"title_en\": \"... or null\", "
        "\"bullet\": \"first bullet point or null\"}.\n"
        "Skip pages without actual news cards (cover, table of contents, etc.).\n"
        "Return ONLY a JSON array. No prose, no markdown.\n\n"
        f"TEXT:\n{joined[:12000]}"
    )
    try:
        resp = quick_llm.invoke(prompt).content
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.strip(), flags=re.M)
        data = json.loads(cleaned)
    except Exception:
        logger.warning("SAVE news card LLM extraction failed")
        return []

    out: list[NewsItem] = []
    when = datetime.combine(brief_date, datetime.min.time().replace(hour=9))
    for entry in data:
        if not isinstance(entry, dict):
            continue
        kr = (entry.get("title_kr") or "").strip()
        en = entry.get("title_en")
        if not kr:
            continue
        headline = f"{kr} — {en}" if en else kr
        out.append(NewsItem(
            headline=headline[:300], source="SAVE",
            published_at=when, url="local://save_brief",
        ))
    return out


# 주간 일정 키워드
_WEEKLY_EVENT_RE = re.compile(
    r"국채\s*경매|FOMC|BOK|연준|금통위|ECB|BOJ|CPI|GDP|"
    r"비농업|payroll|fomc|jobless",
    re.IGNORECASE,
)


def parse_weekly_schedule(
    pages: list[str], brief_date: date,
) -> list[CalendarEvent]:
    """마지막 페이지들에서 '이번 주' 키워드 또는 매크로 이벤트 라인 추출."""
    out: list[CalendarEvent] = []
    for page in pages[-5:]:  # 보통 마지막 페이지에 있음
        if "이번 주" not in page and "주간 일정" not in page:
            continue
        for ln in page.splitlines():
            ln = ln.strip()
            if not _WEEKLY_EVENT_RE.search(ln):
                continue
            if len(ln) < 5 or len(ln) > 200:
                continue
            event_type = "other"
            if "FOMC" in ln.upper() or "연준" in ln:
                event_type = "fomc"
            elif "BOK" in ln.upper() or "금통위" in ln:
                event_type = "bok"
            elif "CPI" in ln.upper():
                event_type = "cpi"
            elif "GDP" in ln.upper():
                event_type = "gdp"
            out.append(CalendarEvent(
                event_date=brief_date + timedelta(days=1),
                region="GLOBAL",
                event_type=event_type,  # type: ignore[arg-type]
                description=ln[:200],
            ))
    return out[:20]


@register_skill(name="ingest_save_brief", category="news")
def ingest_save_brief(
    as_of: date | None = None, quick_llm=None,
    explicit_path: Path | str | None = None,
) -> SaveBriefSnapshot | None:
    """Return None if no file found or empty.

    explicit_path: 테스트에서 fixture 경로를 직접 지정할 때 사용.
    """
    if explicit_path is not None:
        path = Path(explicit_path)
        if not path.exists():
            return None
    else:
        path = find_latest_save_brief(as_of=as_of)
        if path is None:
            return None

    try:
        text = load_save_brief_text(path)
    except Exception as e:
        logger.warning("SAVE brief load failed: %s", e)
        return None

    pages = split_save_brief_pages(text)
    pages_parsed = len(pages)
    pages_total = max(pages_parsed, len(text.split("--- Page ")))

    brief_date = parse_brief_date(text) or (as_of or date.today())

    releases = parse_economic_releases(pages, brief_date)

    # LLM 우선, 실패시 휴리스틱 fallback
    cards = parse_news_cards_with_llm(pages, brief_date, quick_llm)
    if not cards:
        cards = parse_news_cards_heuristic(pages)

    schedule = parse_weekly_schedule(pages, brief_date)

    return SaveBriefSnapshot(
        brief_date=brief_date,
        economic_releases=releases,
        news_cards=cards,
        weekly_schedule=schedule,
        pages_total=pages_total,
        pages_parsed=pages_parsed,
        source_file=str(path),
        source_date=brief_date,
    )
