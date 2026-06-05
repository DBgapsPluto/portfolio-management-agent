from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from tradingagents.schemas.news import CategorizedNewsItem, NewsItem
from tradingagents.skills.news.news_sentiment import (
    compute_news_sentiment_snapshot, score_sentiment,
)


def _ci(
    headline: str = "h",
    category: str = "macro",
    score: float = 0.0,
    when: datetime | None = None,
    themes: list[str] | None = None,
) -> CategorizedNewsItem:
    return CategorizedNewsItem(
        item=NewsItem(
            headline=headline, source="x",
            published_at=when or datetime(2026, 5, 18, 9, 0),
            url="https://e.com",
        ),
        category=category,  # type: ignore[arg-type]
        sentiment_score=score, classifier_source="keyword",
        themes=themes or [],  # type: ignore[arg-type]
    )


def test_snapshot_aggregates_theme_counts():
    """snapshot이 theme별 카운트를 집계한다 (category와 별개 축)."""
    items = [
        _ci("Nvidia AI chip surge", category="corporate", score=0.5, themes=["ai_semis"]),
        _ci("TSMC expands fab", category="corporate", score=0.3, themes=["ai_semis"]),
        _ci("Oil drops on OPEC", category="macro", score=-0.2, themes=["energy"]),
    ]
    snap = compute_news_sentiment_snapshot(items, as_of=date(2026, 6, 5))
    assert snap.theme_counts["ai_semis"] == 2
    assert snap.theme_counts["energy"] == 1
    assert snap.theme_top_headline["ai_semis"]  # 대표 헤드라인 채워짐


def test_snapshot_theme_counts_empty_when_no_themes():
    """테마 태그 없는 뉴스만 있으면 theme_counts 비어있음."""
    snap = compute_news_sentiment_snapshot([_ci("Fed holds")], as_of=date(2026, 6, 5))
    assert snap.theme_counts == {}


def test_score_sentiment_fills_scores_from_llm():
    items = [_ci("CPI up"), _ci("Bad earnings")]
    fake = MagicMock()
    fake.invoke.return_value.content = '[{"idx":0,"score":0.5},{"idx":1,"score":-0.7}]'
    scored = score_sentiment(items, quick_llm=fake)
    assert scored[0].sentiment_score == 0.5
    assert scored[1].sentiment_score == -0.7


def test_score_sentiment_clamps_to_bounds():
    items = [_ci("x")]
    fake = MagicMock()
    fake.invoke.return_value.content = '[{"idx":0,"score":2.0}]'
    scored = score_sentiment(items, quick_llm=fake)
    assert -1.0 <= scored[0].sentiment_score <= 1.0


def test_score_sentiment_llm_failure_fallback_zero():
    items = [_ci("x")]
    fake = MagicMock()
    fake.invoke.side_effect = RuntimeError("api")
    scored = score_sentiment(items, quick_llm=fake)
    assert scored[0].sentiment_score == 0.0


def test_score_sentiment_no_llm_keeps_existing():
    items = [_ci("x", score=0.3)]
    out = score_sentiment(items, quick_llm=None)
    assert out[0].sentiment_score == 0.3


def test_snapshot_empty_input():
    snap = compute_news_sentiment_snapshot([], as_of=date(2026, 5, 18))
    assert snap.dominant_category is None
    assert snap.counts == {}


def test_snapshot_aggregates_counts_and_sentiment():
    items = [
        _ci("policy A", category="policy", score=-0.3),
        _ci("policy B", category="policy", score=-0.5),
        _ci("macro A",  category="macro",  score=+0.1),
        _ci("corp A",   category="corporate", score=+0.7),
    ]
    snap = compute_news_sentiment_snapshot(items, as_of=date(2026, 5, 18))
    assert snap.counts["policy"] == 2
    assert snap.counts["macro"] == 1
    assert snap.dominant_category == "policy"
    assert snap.avg_sentiment["policy"] == pytest.approx(-0.4, 0.01)
    assert snap.avg_sentiment["corporate"] == pytest.approx(0.7, 0.01)
    assert "policy" in snap.top_headline_per_category


def test_snapshot_dispersion_zero_when_one_category():
    items = [_ci("m1", category="macro", score=0.1)]
    snap = compute_news_sentiment_snapshot(items, as_of=date(2026, 5, 18))
    assert snap.sentiment_dispersion == 0.0


def test_snapshot_momentum_detects_rising_category():
    now = datetime(2026, 5, 18, 10, 0)
    # 최근 24h: policy 3개, 직전 7일 daily avg: policy 0.14
    recent = [
        _ci(f"recent policy {i}", category="policy", score=-0.3, when=now - timedelta(hours=i+1))
        for i in range(3)
    ]
    earlier = [
        _ci("old policy", category="policy", score=-0.2, when=now - timedelta(days=4)),
    ]
    snap = compute_news_sentiment_snapshot(recent + earlier, as_of=date(2026, 5, 18))
    assert snap.rising_category == "policy"
