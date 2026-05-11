from tradingagents.dataflows.news_macro import fetch_macro_news as _fetch
from tradingagents.schemas.news import NewsItem
from tradingagents.skills.registry import register_skill


DEFAULT_RSS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^IXIC",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=KRW=X",
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "https://seekingalpha.com/feed.xml",
    "https://www.mk.co.kr/rss/50200011/",
]


@register_skill(name="fetch_macro_news", category="news")
def fetch_macro_news_skill(rss_urls: list[str] | None = None, window_days: int = 7) -> list[NewsItem]:
    return _fetch(rss_urls or DEFAULT_RSS, window_days=window_days)
