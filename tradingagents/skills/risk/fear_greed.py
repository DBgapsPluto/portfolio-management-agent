from datetime import date

import requests

from tradingagents.schemas.risk import SentimentSnapshot
from tradingagents.skills.registry import register_skill


def _scrape_cnn_fg() -> dict | None:
    """Scrape CNN Fear & Greed. Returns None on any failure (D5 tier3)."""
    try:
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("fear_and_greed", {})
    except Exception:
        return None


@register_skill(name="fetch_fear_greed_index", category="risk")
def fetch_fear_greed_index(as_of: date) -> SentimentSnapshot | None:
    """Returns None if CNN F&G unavailable. Caller skips-with-note."""
    raw = _scrape_cnn_fg()
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
