from datetime import date

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
    # 거시·지정학 전용 소스 (2026-06-05) — 종목 편중 feed만으론 이란 전쟁 같은
    # 지정학 이벤트가 빈약. 모두 live 검증. impact-classify 우선순위는
    # categorizer.prioritize_macro_relevant 가 보장.
    "http://feeds.bbci.co.uk/news/world/rss.xml",          # BBC World
    "https://www.aljazeera.com/xml/rss/all.xml",            # Al Jazeera (중동 강점)
    "https://www.cnbc.com/id/100727362/device/rss/rss.html",  # CNBC World
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",   # CNBC Economy
]


@register_skill(name="fetch_macro_news", category="news")
def fetch_macro_news_skill(rss_urls: list[str] | None = None, window_days: int = 7,
                           as_of: date | None = None) -> list[NewsItem]:
    return _fetch(rss_urls or DEFAULT_RSS, window_days=window_days, as_of=as_of)
