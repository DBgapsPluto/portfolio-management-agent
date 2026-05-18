from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tradingagents.schemas.news import CBSpeakerEvent, NewsItem
from tradingagents.skills.news.cb_speaker_tracker import (
    _balance, _detect_speaker, compute_speaker_aggregate,
    extract_speaker_events,
)


def _item(headline: str, when: date = date(2026, 5, 18)) -> NewsItem:
    return NewsItem(
        headline=headline, source="x",
        published_at=datetime.combine(when, datetime.min.time().replace(hour=9)),
        url="https://e.com/x",
    )


def test_detect_speaker_powell():
    det = _detect_speaker("Fed Chair Powell hints at rate cut later this year")
    assert det is not None
    speaker, cb, voting = det
    assert cb == "Fed"
    assert voting is True


def test_detect_speaker_lee_changyong():
    det = _detect_speaker("BOK 이창용 총재, 물가 안정 강조")
    assert det is not None
    _, cb, voting = det
    assert cb == "BOK"
    assert voting is True


def test_detect_speaker_lagarde():
    det = _detect_speaker("ECB's Lagarde reiterates data-dependent stance")
    assert det is not None
    _, cb, _ = det
    assert cb == "ECB"


def test_detect_speaker_none_for_unrelated():
    assert _detect_speaker("Apple beats earnings, raises guidance") is None


def test_extract_skips_non_speaker_news():
    items = [_item("US CPI 3.2% YoY"), _item("Apple buyback")]
    out = extract_speaker_events(items, quick_llm=None)
    assert out == []


def test_extract_classifies_tone_via_llm():
    items = [
        _item("Powell says inflation still too high"),
        _item("ECB's Lagarde signals possible cut"),
    ]
    fake = MagicMock()
    fake.invoke.return_value.content = (
        '[{"idx":0,"tone":"hawkish"},{"idx":1,"tone":"dovish"}]'
    )
    out = extract_speaker_events(items, quick_llm=fake)
    assert len(out) == 2
    assert out[0].tone == "hawkish"
    assert out[1].tone == "dovish"


def test_extract_neutral_fallback_on_llm_failure():
    items = [_item("Powell mentions data dependency")]
    fake = MagicMock()
    fake.invoke.side_effect = RuntimeError("api")
    out = extract_speaker_events(items, quick_llm=fake)
    assert out[0].tone == "neutral"


def test_extract_no_llm_defaults_neutral():
    items = [_item("Powell speech today")]
    out = extract_speaker_events(items, quick_llm=None)
    assert out[0].tone == "neutral"


def test_balance_helper():
    events = [
        CBSpeakerEvent(event_date=date.today(), cb="Fed", speaker="Powell",
                       voting=True, tone="hawkish", headline="h1"),
        CBSpeakerEvent(event_date=date.today(), cb="Fed", speaker="Goolsbee",
                       voting=False, tone="dovish", headline="h2"),
    ]
    assert _balance(events) == pytest.approx(0.0, 0.01)
    assert _balance(events, voting_only=True) == pytest.approx(1.0, 0.01)


def test_aggregate_separates_fed_and_bok_within_7d():
    as_of = date(2026, 5, 18)
    events = [
        CBSpeakerEvent(event_date=as_of, cb="Fed", speaker="Powell",
                       voting=True, tone="hawkish", headline="h1"),
        CBSpeakerEvent(event_date=as_of - timedelta(days=2), cb="BOK",
                       speaker="이창용", voting=True, tone="dovish", headline="h2"),
        CBSpeakerEvent(event_date=as_of - timedelta(days=14), cb="Fed",
                       speaker="Williams", voting=True, tone="dovish", headline="h3"),
    ]
    agg = compute_speaker_aggregate(events, as_of=as_of)
    assert len(agg.fed_speakers_7d) == 1
    assert len(agg.bok_speakers_7d) == 1
    assert agg.fed_tone_balance == 1.0
    assert agg.bok_tone_balance == -1.0
    assert agg.fed_voting_balance == 1.0


def test_aggregate_empty():
    agg = compute_speaker_aggregate([], as_of=date(2026, 5, 18))
    assert agg.fed_tone_balance == 0.0
    assert agg.bok_tone_balance == 0.0
