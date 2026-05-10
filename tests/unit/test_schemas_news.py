import pytest
from datetime import datetime
from pydantic import ValidationError
from tradingagents.schemas.news import (
    CalendarEvent,
    NewsItem,
    ImpactAssessment,
    RankedNews,
)


def test_news_headline_only():
    item = NewsItem(
        headline="Fed signals 25bp cut at next meeting",
        source="Reuters",
        published_at=datetime(2026, 5, 10, 14, 30),
        url="https://reuters.com/x",
    )
    assert item.headline.startswith("Fed")


def test_impact_assessment_schema():
    impact = ImpactAssessment(
        asset_classes_affected=["us_bond", "us_equity"],
        direction="up",
        severity=4,
        reasoning="Lower rates positive for bonds and equities",
    )
    assert impact.severity == 4
    assert "us_bond" in impact.asset_classes_affected


def test_calendar_event_complete():
    event = CalendarEvent(
        event_date=datetime(2026, 5, 15).date(),
        region="US",
        event_type="fomc",
        description="FOMC meeting and rate decision",
        consensus="25bp cut expected",
    )
    assert event.event_type == "fomc"
    assert event.region == "US"


def test_calendar_event_no_consensus():
    event = CalendarEvent(
        event_date=datetime(2026, 5, 15).date(),
        region="KR",
        event_type="bok",
        description="BOK rate decision",
    )
    assert event.consensus is None


def test_impact_assessment_multiple_asset_classes():
    impact = ImpactAssessment(
        asset_classes_affected=["us_equity", "us_bond", "fx", "commodity"],
        direction="down",
        severity=5,
        reasoning="Major geopolitical shock affects all asset classes",
    )
    assert len(impact.asset_classes_affected) == 4
    assert impact.severity == 5


def test_impact_assessment_direction_literal():
    for direction in ["up", "down", "neutral"]:
        impact = ImpactAssessment(
            asset_classes_affected=["us_equity"],
            direction=direction,
            severity=3,
            reasoning="Test",
        )
        assert impact.direction == direction


def test_impact_assessment_rejects_invalid_direction():
    with pytest.raises(ValidationError):
        ImpactAssessment(
            asset_classes_affected=["us_equity"],
            direction="sideways",
            severity=3,
            reasoning="Test",
        )


def test_impact_assessment_severity_bounds():
    # Valid bounds: 1-5
    for severity in [1, 2, 3, 4, 5]:
        impact = ImpactAssessment(
            asset_classes_affected=["us_equity"],
            direction="up",
            severity=severity,
            reasoning="Test",
        )
        assert impact.severity == severity

    # Invalid: below 1
    with pytest.raises(ValidationError):
        ImpactAssessment(
            asset_classes_affected=["us_equity"],
            direction="up",
            severity=0,
            reasoning="Test",
        )

    # Invalid: above 5
    with pytest.raises(ValidationError):
        ImpactAssessment(
            asset_classes_affected=["us_equity"],
            direction="up",
            severity=6,
            reasoning="Test",
        )


def test_impact_assessment_min_asset_classes():
    # Should require at least 1
    with pytest.raises(ValidationError):
        ImpactAssessment(
            asset_classes_affected=[],
            direction="up",
            severity=3,
            reasoning="Test",
        )


def test_impact_assessment_max_asset_classes():
    # Should reject more than 4
    with pytest.raises(ValidationError):
        ImpactAssessment(
            asset_classes_affected=["us_equity", "us_bond", "fx", "commodity", "gold"],
            direction="up",
            severity=3,
            reasoning="Test",
        )


def test_ranked_news_complete():
    item = NewsItem(
        headline="Fed cuts rates by 25bp",
        source="Bloomberg",
        published_at=datetime(2026, 5, 10, 10, 0),
        url="https://bloomberg.com/x",
    )
    impact = ImpactAssessment(
        asset_classes_affected=["us_bond", "us_equity"],
        direction="up",
        severity=4,
        reasoning="Lower rates supportive",
    )
    ranked = RankedNews(
        item=item,
        impact=impact,
        rank_score=4.8,
    )
    assert ranked.rank_score == 4.8
    assert ranked.item.headline == "Fed cuts rates by 25bp"
    assert ranked.impact.severity == 4


def test_news_item_plain_url_string():
    """URLs stored as plain str for resilience to bad sources."""
    item = NewsItem(
        headline="Test headline",
        source="TestSource",
        published_at=datetime(2026, 5, 10, 0, 0),
        url="not-a-valid-url",  # Should accept even malformed URLs
    )
    assert item.url == "not-a-valid-url"


def test_headline_max_length():
    """Headlines limited to 300 chars."""
    long_headline = "A" * 300
    item = NewsItem(
        headline=long_headline,
        source="Reuters",
        published_at=datetime(2026, 5, 10, 0, 0),
        url="https://reuters.com/x",
    )
    assert len(item.headline) == 300

    # Should reject > 300
    with pytest.raises(ValidationError):
        NewsItem(
            headline="A" * 301,
            source="Reuters",
            published_at=datetime(2026, 5, 10, 0, 0),
            url="https://reuters.com/x",
        )


def test_calendar_event_description_max_length():
    """Descriptions limited to 200 chars."""
    desc = "B" * 200
    event = CalendarEvent(
        event_date=datetime(2026, 5, 15).date(),
        region="US",
        event_type="fomc",
        description=desc,
    )
    assert len(event.description) == 200

    # Should reject > 200
    with pytest.raises(ValidationError):
        CalendarEvent(
            event_date=datetime(2026, 5, 15).date(),
            region="US",
            event_type="fomc",
            description="B" * 201,
        )


def test_impact_assessment_reasoning_max_length():
    """Reasoning limited to 200 chars."""
    reasoning = "C" * 200
    impact = ImpactAssessment(
        asset_classes_affected=["us_equity"],
        direction="up",
        severity=3,
        reasoning=reasoning,
    )
    assert len(impact.reasoning) == 200

    # Should reject > 200
    with pytest.raises(ValidationError):
        ImpactAssessment(
            asset_classes_affected=["us_equity"],
            direction="up",
            severity=3,
            reasoning="C" * 201,
        )


def test_asset_class_types():
    """Test all valid asset class literals."""
    valid_classes = [
        "kr_equity", "us_equity", "global_equity",
        "kr_bond", "us_bond",
        "fx", "commodity", "gold",
    ]
    for ac in valid_classes:
        impact = ImpactAssessment(
            asset_classes_affected=[ac],
            direction="up",
            severity=3,
            reasoning="Test",
        )
        assert ac in impact.asset_classes_affected


def test_calendar_event_regions():
    """Test all valid region literals."""
    valid_regions = ["US", "KR", "EU", "JP", "CN", "GLOBAL"]
    for region in valid_regions:
        event = CalendarEvent(
            event_date=datetime(2026, 5, 15).date(),
            region=region,
            event_type="fomc",
            description="Test event",
        )
        assert event.region == region


def test_calendar_event_types():
    """Test all valid event type literals."""
    valid_types = ["fomc", "bok", "cpi", "gdp", "employment", "pmi", "other"]
    for et in valid_types:
        event = CalendarEvent(
            event_date=datetime(2026, 5, 15).date(),
            region="US",
            event_type=et,
            description="Test event",
        )
        assert event.event_type == et
