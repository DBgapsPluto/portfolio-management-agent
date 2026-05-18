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


# Speaker → (central_bank, voting_2026)
# voting은 시간에 따라 바뀌므로 (Fed regional president rotation 등) 정적 매핑은
# 2026 시점 단순화. 모르면 None.
SPEAKER_DIRECTORY: dict[str, tuple[CentralBank, bool | None]] = {
    # Fed - 영구 voting
    "powell":    ("Fed", True),
    "jefferson": ("Fed", True),
    "williams":  ("Fed", True),
    "bowman":    ("Fed", True),
    "cook":      ("Fed", True),
    "kugler":    ("Fed", True),
    "waller":    ("Fed", True),
    # Fed - 2026 rotating voting (예시 — 정확치는 매년 변경)
    "goolsbee":  ("Fed", False),
    "bostic":    ("Fed", False),
    "schmid":    ("Fed", False),
    "musalem":   ("Fed", False),
    "barkin":    ("Fed", False),
    "logan":     ("Fed", False),
    "daly":      ("Fed", False),
    "kashkari":  ("Fed", False),
    "harker":    ("Fed", False),
    "collins":   ("Fed", False),
    # BOK
    "이창용":     ("BOK", True),
    "rhee":      ("BOK", True),
    # ECB
    "lagarde":   ("ECB", True),
    "schnabel":  ("ECB", True),
    "lane":      ("ECB", True),
    # BOJ
    "ueda":      ("BOJ", True),
    "uchida":    ("BOJ", True),
    # BoE
    "bailey":    ("BoE", True),
    # PBoC
    "pan":       ("PBoC", True),
}


def _detect_speaker(text: str) -> tuple[str, CentralBank, bool | None] | None:
    lower = text.lower()
    for name, (cb, voting) in SPEAKER_DIRECTORY.items():
        if name in lower:
            display = name.title() if name.isascii() else name
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
) -> list[CBSpeakerEvent]:
    """뉴스에서 CB speaker 매칭 + tone 분류."""
    matched: list[tuple[NewsItem, str, CentralBank, bool | None]] = []
    for item in items:
        det = _detect_speaker(item.headline)
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
