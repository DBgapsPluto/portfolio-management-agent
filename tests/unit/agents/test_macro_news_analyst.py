from datetime import date, datetime
from unittest.mock import MagicMock

from tradingagents.agents.analysts.macro_news_analyst import (
    _summarize_sentiment, create_macro_news_analyst,
)
from tradingagents.schemas.news import (
    ImpactAssessment, NewsItem, NewsSentimentSnapshot,
)
from tradingagents.schemas.reports import NewsReport


def test_summarize_sentiment_includes_themes():
    """섹터/투자 테마 분포가 stage2 요약(news_summary)에 포함되어야 한다 —
    stage2가 거시·지정학뿐 아니라 AI·에너지 등 테마 지형도 참고하도록."""
    snap = NewsSentimentSnapshot(
        counts={"corporate": 3, "geopolitical": 1},
        avg_sentiment={"corporate": 0.2, "geopolitical": -0.5},
        dominant_category="corporate", sentiment_dispersion=0.3,
        top_headline_per_category={"corporate": "Nvidia beats"},
        theme_counts={"ai_semis": 3, "energy": 1},
        theme_top_headline={"ai_semis": "Nvidia AI chip surge", "energy": "Oil falls 3%"},
        count_change_vs_7d={}, rising_category=None,
        source_date=date(2026, 6, 5),
    )
    out = _summarize_sentiment(snap)
    assert "Themes" in out
    assert "ai_semis" in out
    assert "energy" in out


def test_summarize_sentiment_no_themes_omits_theme_block():
    """테마가 없으면 테마 블록을 넣지 않는다 (잡음 방지)."""
    snap = NewsSentimentSnapshot(
        counts={"macro": 2}, avg_sentiment={"macro": 0.1},
        dominant_category="macro", sentiment_dispersion=0.0,
        top_headline_per_category={"macro": "CPI inline"},
        theme_counts={}, theme_top_headline={},
        count_change_vs_7d={}, rising_category=None,
        source_date=date(2026, 6, 5),
    )
    out = _summarize_sentiment(snap)
    assert "Themes" not in out


def test_news_analyst_returns_report(monkeypatch):
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    quick_llm.invoke.return_value.content = "news narrative"

    fake_items = [
        NewsItem(
            headline="Fed signals 25bp cut",
            source="Reuters",
            published_at=datetime(2026, 5, 10, 14, 30),
            url="https://example.com",
        ),
    ]
    fake_impact = ImpactAssessment(
        asset_classes_affected=["us_bond"],
        direction="up", severity=4,
        reasoning="rate cut",
    )

    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_news_analyst.fetch_event_calendar_skill",
        lambda d, days: [],
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_news_analyst.fetch_macro_news_skill",
        lambda **kw: fake_items,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_news_analyst.classify_event_impact",
        lambda *args, **kwargs: fake_impact,
    )

    node = create_macro_news_analyst(quick_llm, deep_llm)
    result = node({"as_of_date": "2026-05-10"})
    assert "news_report" in result
    assert isinstance(result["news_report"], NewsReport)
    assert len(result["news_report"].ranked_news) >= 1
