"""Tier-4 — Central bank speaker tracker (hawkish/dovish tone aggregate).

이전 분석가가 안 보는 차원:
- macro_quant event_calendar는 일정만 (발언 톤은 안 봄)
- market_risk는 vol/credit만
- macro_news 기존 ranker는 severity만 (매파-비둘기 분류 X)
"""
import json
import re
from datetime import date, datetime, timedelta
from typing import Literal

from tradingagents.schemas.news import (
    CBSpeakerEvent, CentralBank, NewsItem, SpeakerTone, SpeakerToneAggregate,
)
from tradingagents.skills.registry import register_skill


# Speaker → central_bank (구성원 매핑). voting 여부는 연도별 별도 lookup.
# 2026-05 hardcode #1 fix: 이전엔 voting flag가 dict 안에 박혀 매년 1월 Fed
# regional president 회전을 따라가지 못했음. 이제 SPEAKER_TO_CB는 영속적 매핑,
# FED_VOTING_BY_YEAR가 연도별 voting set을 보유. as_of.year로 lookup.
SPEAKER_TO_CB: dict[str, CentralBank] = {
    # Fed Board of Governors (항상 voting — 정원 7명, 임명/사임 시 update)
    "powell":    "Fed",
    "jefferson": "Fed",
    "williams":  "Fed",   # NY Fed president (영구 voting)
    "bowman":    "Fed",
    "cook":      "Fed",
    "kugler":    "Fed",
    "waller":    "Fed",
    # Fed regional presidents (voting은 매년 회전 — 아래 FED_VOTING_BY_YEAR 참조)
    "goolsbee":  "Fed",   # Chicago
    "bostic":    "Fed",   # Atlanta
    "schmid":    "Fed",   # Kansas City
    "musalem":   "Fed",   # St. Louis
    "barkin":    "Fed",   # Richmond
    "logan":     "Fed",   # Dallas
    "daly":      "Fed",   # San Francisco
    "kashkari":  "Fed",   # Minneapolis
    "harker":    "Fed",   # Philadelphia
    "collins":   "Fed",   # Boston
    "hammack":   "Fed",   # Cleveland
    "paulson":   "Fed",   # 다음 후보 (placeholder, 임명 시 확정)
    # BOK
    "이창용":     "BOK",
    "rhee":      "BOK",
    # ECB
    "lagarde":   "ECB",
    "schnabel":  "ECB",
    "lane":      "ECB",
    # BOJ
    "ueda":      "BOJ",
    "uchida":    "BOJ",
    # BoE
    "bailey":    "BoE",
    # PBoC
    "pan":       "PBoC",
}


# Fed regional president voting rotation — 매년 1월 회전.
# Board of Governors는 항상 voting (7명) + NY Fed president는 영구 voting.
# 나머지 11개 regional presidents 중 4명만 매년 voting (4-1-1-1-1 rotation).
# 참고: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
#
# 이 dict는 매년 1월에 update 필요. 모르는 연도는 가장 가까운 연도의 voting list
# 사용 (best-effort fallback). 정확한 신호 위해서는 연 1회 reviewed가 좋음.
_FED_PERMANENT_VOTING = {
    "powell", "jefferson", "williams", "bowman", "cook", "kugler", "waller",
}

FED_VOTING_BY_YEAR: dict[int, set[str]] = {
    # 2026 voting regional presidents (예시 — 실제 매년 변경. 확인 필요):
    # cf. Atlanta, Boston, Chicago, St. Louis (일반적 4-bank rotation pattern)
    2026: _FED_PERMANENT_VOTING | {"bostic", "collins", "goolsbee", "musalem"},
    # 2027부터: 다음 4 banks (Cleveland, Philadelphia, Dallas, Minneapolis 추정)
    2027: _FED_PERMANENT_VOTING | {"hammack", "harker", "logan", "kashkari"},
    # 2028: Atlanta, Boston, Chicago, St. Louis 순환 가정
    2028: _FED_PERMANENT_VOTING | {"bostic", "collins", "goolsbee", "musalem"},
}


def _is_fed_voting(speaker_key: str, year: int) -> bool:
    """as_of 연도의 Fed voting set에서 lookup. 등록 안 된 연도는 가장 가까운 연도."""
    if year in FED_VOTING_BY_YEAR:
        return speaker_key in FED_VOTING_BY_YEAR[year]
    # Best-effort: 가장 가까운 등록 연도 사용
    closest = min(FED_VOTING_BY_YEAR.keys(), key=lambda y: abs(y - year))
    return speaker_key in FED_VOTING_BY_YEAR[closest]


def _voting_for(speaker_key: str, cb: CentralBank, year: int) -> bool | None:
    """Fed regional/Board는 연도별, 그 외 CB는 정원 voting=True."""
    if cb == "Fed":
        return _is_fed_voting(speaker_key, year)
    # 다른 CB는 위원회 정원 — Powell이 임명한 ECB/BOJ governors 등 모두 voting.
    # 사임/교체 시 SPEAKER_TO_CB에서 빼면 됨.
    return True


# Backward-compat: 외부에서 SPEAKER_DIRECTORY import하는 코드를 위해 dict 유지.
# voting flag는 현재 연도의 best guess.
from datetime import date as _date  # noqa: E402
_DEFAULT_YEAR = _date.today().year
SPEAKER_DIRECTORY: dict[str, tuple[CentralBank, bool | None]] = {
    name: (cb, _voting_for(name, cb, _DEFAULT_YEAR))
    for name, cb in SPEAKER_TO_CB.items()
}


def _detect_speaker(
    text: str, year: int | None = None,
) -> tuple[str, CentralBank, bool | None] | None:
    """뉴스 텍스트에서 speaker 매칭. as_of year 제공 시 연도별 voting 적용."""
    lower = text.lower()
    use_year = year if year is not None else _date.today().year
    for name, cb in SPEAKER_TO_CB.items():
        if name in lower:
            display = name.title() if name.isascii() else name
            voting = _voting_for(name, cb, use_year)
            return display, cb, voting
    return None


def _llm_classify_tone_batch(
    quick_llm, headlines: list[str],
) -> list[SpeakerTone]:
    if not headlines:
        return []
    prompt = (
        "Classify each central bank speaker headline by monetary policy tone.\n"
        "- hawkish: leans toward tighter policy (more cuts opposed, rate hikes, "
        "inflation concern emphasized)\n"
        "- dovish: leans toward looser policy (cuts supported, growth concern "
        "emphasized, easing signals)\n"
        "- neutral: data-dependent or balanced\n\n"
        "Return ONLY a JSON array like "
        "[{\"idx\":0,\"tone\":\"hawkish\"}, ...]. No prose.\n\n"
        "Headlines:\n"
        + "\n".join(f"{i}. {h}" for i, h in enumerate(headlines))
    )
    try:
        resp = quick_llm.invoke(prompt).content
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.strip(), flags=re.M)
        data = json.loads(cleaned)
        result: list[SpeakerTone] = ["neutral"] * len(headlines)
        valid = {"hawkish", "neutral", "dovish"}
        for entry in data:
            idx = int(entry.get("idx", -1))
            tone = entry.get("tone", "neutral")
            if 0 <= idx < len(headlines) and tone in valid:
                result[idx] = tone  # type: ignore[assignment]
        return result
    except Exception:
        return ["neutral"] * len(headlines)


def extract_speaker_events(
    items: list[NewsItem], quick_llm=None, batch_size: int = 10,
    as_of: date | None = None,
) -> list[CBSpeakerEvent]:
    """뉴스에서 CB speaker 매칭 + tone 분류.

    as_of: 연도별 Fed voting rotation 정확 적용용. 미제공 시 오늘 기준.
    """
    matched: list[tuple[NewsItem, str, CentralBank, bool | None]] = []
    year_for_lookup = (as_of.year if as_of is not None else _date.today().year)
    for item in items:
        det = _detect_speaker(item.headline, year=year_for_lookup)
        if det is None:
            continue
        speaker, cb, voting = det
        matched.append((item, speaker, cb, voting))

    if not matched:
        return []

    tones: list[SpeakerTone]
    if quick_llm is None:
        tones = ["neutral"] * len(matched)
    else:
        tones = []
        for start in range(0, len(matched), batch_size):
            batch = matched[start:start + batch_size]
            tones.extend(_llm_classify_tone_batch(
                quick_llm, [m[0].headline for m in batch],
            ))

    out: list[CBSpeakerEvent] = []
    for (item, speaker, cb, voting), tone in zip(matched, tones):
        out.append(CBSpeakerEvent(
            event_date=item.published_at.date(),
            cb=cb, speaker=speaker, voting=voting,
            tone=tone, headline=item.headline[:300],
        ))
    return out


_TONE_SCORE = {"hawkish": 1.0, "neutral": 0.0, "dovish": -1.0}


def _balance(events: list[CBSpeakerEvent], voting_only: bool = False) -> float:
    filtered = [e for e in events if (not voting_only or e.voting is True)]
    if not filtered:
        return 0.0
    return sum(_TONE_SCORE[e.tone] for e in filtered) / len(filtered)


@register_skill(name="compute_speaker_aggregate", category="news")
def compute_speaker_aggregate(
    events: list[CBSpeakerEvent], as_of: date,
) -> SpeakerToneAggregate:
    cutoff = as_of - timedelta(days=7)
    recent = [e for e in events if e.event_date >= cutoff]

    fed = [e for e in recent if e.cb == "Fed"]
    bok = [e for e in recent if e.cb == "BOK"]
    other = [e for e in recent if e.cb not in ("Fed", "BOK")]

    return SpeakerToneAggregate(
        fed_speakers_7d=fed,
        bok_speakers_7d=bok,
        other_speakers_7d=other,
        fed_tone_balance=_balance(fed),
        bok_tone_balance=_balance(bok),
        fed_voting_balance=_balance(fed, voting_only=True),
        source_date=as_of,
    )
