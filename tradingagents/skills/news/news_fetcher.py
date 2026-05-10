from tradingagents.dataflows.news_macro import fetch_macro_news as _fetch
from tradingagents.schemas.news import NewsItem
from tradingagents.skills.registry import register_skill


DEFAULT_RSS = [
    "https://www.reuters.com/markets/rss",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC",
]


@register_skill(name="fetch_macro_news", category="news")
def fetch_macro_news_skill(rss_urls: list[str] | None = None, window_days: int = 7) -> list[NewsItem]:
    return _fetch(rss_urls or DEFAULT_RSS, window_days=window_days)
