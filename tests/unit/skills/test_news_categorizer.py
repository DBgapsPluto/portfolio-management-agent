from datetime import datetime

from unittest.mock import MagicMock

from tradingagents.schemas.news import NewsItem
from tradingagents.skills.news.categorizer import (
    _keyword_classify, _keyword_themes, categorize_news, prioritize_macro_relevant,
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


def test_prioritize_macro_relevant_lifts_geopolitical_above_stock_volume():
    """종목/실적 뉴스가 feed 앞자리를 채우고 거시·지정학 뉴스가 뒤에 묻혀도,
    재배치 후 거시·지정학 뉴스가 budget(앞 N건) 안에 들어와야 한다.

    2026-06-05 실측: 종목 헤드라인이 impact-classify cap(30)을 다 차지해 진짜
    이란 뉴스(위치 51)가 ranked_news에 못 들던 버그의 회귀 가드.
    """
    stock = [_item(f"Company{i} earnings beat, revenue guidance raised") for i in range(20)]
    iran = _item("Trump weighs strike on Iran nuclear site as tensions rise")
    fed = _item("Fed signals rate cut after CPI miss")
    items = stock + [iran, fed]  # 거시·지정학은 맨 뒤

    out = prioritize_macro_relevant(items)

    top2 = [it.headline for it in out[:2]]
    assert any("Iran" in h for h in top2)
    assert any("rate cut" in h for h in top2)


def test_prioritize_macro_relevant_is_stable_within_groups():
    """같은 관련성 그룹 내에서는 원래 순서를 보존(stable)한다."""
    a = _item("Fed rate cut imminent")        # relevant (policy)
    b = _item("CPI rises above forecast")      # relevant (macro)
    c = _item("Apple earnings beat")           # not relevant (corporate)
    d = _item("Tesla guidance raised")         # not relevant (corporate)
    out = prioritize_macro_relevant([c, a, d, b])
    assert [it.headline for it in out] == [a.headline, b.headline, c.headline, d.headline]


def test_prioritize_macro_relevant_preserves_all_items():
    """재배치는 항목을 추가·삭제하지 않는다 (순열만)."""
    items = [_item("Fed rate cut"), _item("Apple earnings"), _item("Russia war escalates")]
    out = prioritize_macro_relevant(items)
    assert len(out) == len(items)
    assert {it.headline for it in out} == {it.headline for it in items}


# ---------- Theme tagging (sector/investment 축, category와 직교) ----------


def test_keyword_themes_ai_semis():
    assert "ai_semis" in _keyword_themes("Nvidia and Broadcom lead chip rally on AI demand")


def test_keyword_themes_multiple_orthogonal():
    """한 뉴스가 여러 테마를 동시에 가질 수 있다 (직교 축)."""
    themes = _keyword_themes("Tesla battery costs fall as oil prices slide")
    assert "ev_battery" in themes
    assert "energy" in themes


def test_keyword_themes_empty_when_no_sector():
    """섹터 테마가 없는 순수 거시 뉴스는 빈 set."""
    assert _keyword_themes("Fed holds rates steady amid mixed jobs data") == set()


def test_categorize_news_tags_themes_alongside_category():
    """category(성격)와 themes(섹터)는 독립적으로 채워진다."""
    out = categorize_news([_item("Nvidia earnings beat on AI chip demand")], quick_llm=None)
    assert out[0].category == "corporate"   # earnings → 성격
    assert "ai_semis" in out[0].themes       # AI/chip → 테마


def test_categorize_news_themes_default_empty():
    """섹터 무관 뉴스는 themes 빈 list."""
    out = categorize_news([_item("Fed signals rate cut")], quick_llm=None)
    assert out[0].themes == []
