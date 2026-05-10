from unittest.mock import patch

from tradingagents.skills.news.news_fetcher import fetch_macro_news_skill


def test_news_fetcher_uses_default_rss():
    with patch("tradingagents.skills.news.news_fetcher._fetch", return_value=[]) as mock_fetch:
        fetch_macro_news_skill()
    mock_fetch.assert_called_once()
    args, kwargs = mock_fetch.call_args
    assert isinstance(args[0], list)
    assert len(args[0]) > 0  # default RSS URLs used
