"""CNN Fear & Greed Index scraper — with TieredCache."""
import json
import logging
from datetime import date
from pathlib import Path

import requests

from tradingagents.dataflows.cache import TieredCache
from tradingagents.dataflows.pit_guard import is_pit_stale
from tradingagents.dataflows.series_cache import resolve_cache_dir
from tradingagents.schemas.risk import SentimentSnapshot
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


_CNN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
}


def _scrape_cnn_fg() -> dict | None:
    """Scrape CNN Fear & Greed. Returns None on any failure (D5 tier3).

    CNN blocks default Python/urllib User-Agents with "I'm a teapot." — must
    impersonate a real browser.
    """
    try:
        r = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            timeout=10, headers=_CNN_HEADERS,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("fear_and_greed", {})
    except Exception as e:
        logger.warning("CNN F&G scrape failed: %s", e)
        return None


def _classify(raw: dict, as_of: date) -> SentimentSnapshot | None:
    if raw is None:
        return None
    current = int(raw.get("score", 50))
    label_map = {
        (0, 25): "extreme_fear", (25, 45): "fear",
        (45, 55): "neutral", (55, 75): "greed", (75, 101): "extreme_greed",
    }
    label = next(v for (lo, hi), v in label_map.items() if lo <= current < hi)
    prev = float(raw.get("previous_close", current))
    trend = "rising" if current > prev else "falling" if current < prev else "flat"
    return SentimentSnapshot(
        index_name="fear_greed_cnn", current_value=current,
        label=label, trend_7d=trend, source_date=as_of,
    )


@register_skill(name="fetch_fear_greed_index", category="risk")
def fetch_fear_greed_index(
    as_of: date, use_cache: bool = True, max_staleness: int = 3,
) -> SentimentSnapshot | None:
    """CNN F&G index with cache.

    Cache: ~/.tradingagents/cache/cnn_fear_greed/score/{as_of}.json
    max_staleness=3 (sentiment 데이터는 빠르게 stale).
    Returns None if both live and cache miss.
    """
    if is_pit_stale(as_of):
        return None
    if not use_cache:
        return _classify(_scrape_cnn_fg(), as_of)

    cache_dir = resolve_cache_dir() / "cnn_fear_greed"
    cache = TieredCache(cache_dir, name="score")

    # Cache-first
    cached = cache.read(as_of)
    if cached is not None:
        return _classify(cached, as_of)

    # Live + fallback
    raw = _scrape_cnn_fg()
    if raw is not None:
        cache.write(as_of, raw)
        return _classify(raw, as_of)

    # Stale fallback
    from datetime import timedelta
    for delta in range(1, max_staleness + 1):
        d = as_of - timedelta(days=delta)
        old = cache.read(d)
        if old is not None:
            logger.warning(
                "CNN F&G stale fallback (staleness=%dd from %s)", delta, d,
            )
            return _classify(old, as_of)

    return None
