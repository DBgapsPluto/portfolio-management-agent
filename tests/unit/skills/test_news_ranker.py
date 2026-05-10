from datetime import datetime, timedelta

from tradingagents.schemas.news import NewsItem, ImpactAssessment
from tradingagents.skills.news.ranker import dedupe_rank_news


def _item(headline: str, hours_ago: int = 1) -> NewsItem:
    return NewsItem(
        headline=headline, source="Reuters",
        published_at=datetime.utcnow() - timedelta(hours=hours_ago),
        url="https://example.com",
    )


def test_opposite_direction_news_not_deduped():
    """REGRESSION: 'Fed cuts' (direction=up) vs 'Fed hikes' (direction=down)
    have ~92% string similarity but opposite market impact.
    Direction-aware dedup must keep BOTH."""
    items = [
        _item("Fed cuts rates by 25bp", 2),
        _item("Fed hikes rates by 25bp", 1),
    ]
    impacts = {
        "Fed cuts rates by 25bp": ImpactAssessment(
            asset_classes_affected=["us_bond", "us_equity"],
            direction="up", severity=4, reasoning="rate cut",
        ),
        "Fed hikes rates by 25bp": ImpactAssessment(
            asset_classes_affected=["us_bond", "us_equity"],
            direction="down", severity=4, reasoning="rate hike",
        ),
    }
    ranked = dedupe_rank_news(items, impacts, top_n=10)
    assert len(ranked) == 2  # both kept


def test_same_event_deduped():
    """Same direction + similar headlines + overlapping asset classes → dedup."""
    items = [
        _item("Fed cuts rates by 25bp", 2),
        _item("Fed cuts interest rates by 25bp", 1),  # very similar wording
    ]
    impacts = {
        "Fed cuts rates by 25bp": ImpactAssessment(
            asset_classes_affected=["us_bond", "us_equity"],
            direction="up", severity=4, reasoning="x",
        ),
        "Fed cuts interest rates by 25bp": ImpactAssessment(
            asset_classes_affected=["us_bond", "us_equity"],
            direction="up", severity=4, reasoning="y",
        ),
    }
    ranked = dedupe_rank_news(items, impacts, top_n=10)
    assert len(ranked) == 1
