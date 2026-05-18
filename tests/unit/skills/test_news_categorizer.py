from datetime import datetime

from unittest.mock import MagicMock

from tradingagents.schemas.news import NewsItem
from tradingagents.skills.news.categorizer import (
    _keyword_classify, categorize_news,
)


def _item(headline: str) -> NewsItem:
    return NewsItem(
        headline=headline, source="test",
        published_at=datetime(2026, 5, 18, 9, 0),
        url="https://example.com/x",
    )


def test_keyword_classify_policy():
    cat, hits = _keyword_classify("Fed Chair Powell hints at rate cut")
    assert cat == "policy"
    assert hits >= 2  # "fed", "rate cut"


def test_keyword_classify_macro():
    cat, _ = _keyword_classify("US CPI rises 3.2% YoY, above forecast")
    assert cat == "macro"


def test_keyword_classify_corporate():
    cat, _ = _keyword_classify("Ackman buys Microsoft, earnings beat consensus")
    assert cat == "corporate"


def test_keyword_classify_geopolitical():
    cat, _ = _keyword_classify("Russia escalates war in Ukraine; sanctions tighten")
    assert cat == "geopolitical"


def test_keyword_classify_market_commentary():
    cat, _ = _keyword_classify(
        "Goldman raises S&P 500 target to 7,500 on earnings outlook"
    )
    assert cat == "market_commentary"


def test_keyword_classify_returns_none_for_unrelated():
    cat, hits = _keyword_classify("Random unrelated text about cats and dogs")
    assert cat is None or hits == 0


def test_categorize_news_keyword_only_no_llm():
    items = [
        _item("Fed hikes rates by 25bp"),
        _item("US payrolls miss estimates"),
        _item("Goldman downgrades Tesla"),
    ]
    out = categorize_news(items, quick_llm=None)
    assert len(out) == 3
    assert out[0].category == "policy"
    assert out[1].category == "macro"
    assert out[2].category == "market_commentary"
    assert all(c.classifier_source == "keyword" for c in out)


def test_categorize_news_llm_fallback():
    items = [_item("Some opaque headline X Y Z")]
    fake_llm = MagicMock()
    fake_llm.invoke.return_value.content = '[{"idx": 0, "category": "geopolitical"}]'
    out = categorize_news(items, quick_llm=fake_llm)
    assert out[0].category == "geopolitical"
    assert out[0].classifier_source == "llm"


def test_categorize_news_llm_failure_defaults_to_macro():
    items = [_item("Some opaque headline X Y Z")]
    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = RuntimeError("API down")
    out = categorize_news(items, quick_llm=fake_llm)
    assert out[0].category == "macro"  # fallback default


def test_categorize_news_mixed_keyword_and_llm():
    items = [
        _item("Fed rate cut imminent"),     # keyword
        _item("Random gibberish 12345"),     # llm
    ]
    fake_llm = MagicMock()
    fake_llm.invoke.return_value.content = '[{"idx": 0, "category": "corporate"}]'
    out = categorize_news(items, quick_llm=fake_llm)
    assert out[0].category == "policy"
    assert out[0].classifier_source == "keyword"
    assert out[1].category == "corporate"
    assert out[1].classifier_source == "llm"
