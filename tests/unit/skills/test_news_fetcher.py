from unittest.mock import patch

from tradingagents.skills.news.news_fetcher import fetch_macro_news_skill


def test_news_fetcher_uses_default_rss():
    with patch("tradingagents.skills.news.news_fetcher._fetch", return_value=[]) as mock_fetch:
        fetch_macro_news_skill()
    mock_fetch.assert_called_once()
    args, kwargs = mock_fetch.call_args
    assert isinstance(args[0], list)
    assert len(args[0]) > 0  # default RSS URLs used


def test_default_rss_includes_macro_geopolitical_sources():
    """거시·지정학 전용 소스(BBC World, Al Jazeera)가 DEFAULT_RSS에 포함되어야
    한다 — 종목 편중 feed만으로는 지정학 뉴스 커버리지가 부족 (2026-06-05 실측:
    161건 중 지정학 15건, 그나마 cap 밖으로 잘림)."""
    from tradingagents.skills.news.news_fetcher import DEFAULT_RSS

    joined = " ".join(DEFAULT_RSS).lower()
    assert "bbci.co.uk" in joined
    assert "aljazeera" in joined
