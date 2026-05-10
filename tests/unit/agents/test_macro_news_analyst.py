from datetime import datetime
from unittest.mock import MagicMock

from tradingagents.agents.analysts.macro_news_analyst import create_macro_news_analyst
from tradingagents.schemas.news import NewsItem, ImpactAssessment
from tradingagents.schemas.reports import NewsReport


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
