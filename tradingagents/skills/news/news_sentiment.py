"""Tier-3 — News sentiment + category aggregate snapshot.

LLM-only sentiment (batch). FinBERT 의존성 추가 없이 quick_llm으로 한/영 처리.
"""
import json
import re
from datetime import date, datetime, timedelta
from statistics import mean, stdev

from tradingagents.schemas.news import (
    CategorizedNewsItem, NewsCategory, NewsSentimentSnapshot,
)
from tradingagents.skills.registry import register_skill


def _llm_score_batch(quick_llm, headlines: list[str]) -> list[float]:
    """Sentiment score [-1, +1]. 실패 시 0.0으로 fallback."""
    if not headlines:
        return []
    prompt = (
        "You are a financial sentiment scorer. For each headline, output a "
        "float in [-1.0, +1.0] where -1 is very negative for risk assets, "
        "0 is neutral, +1 is very positive.\n\n"
        "Return ONLY a JSON array like "
        "[{\"idx\": 0, \"score\": -0.4}, ...]. No prose.\n\nHeadlines:\n"
        + "\n".join(f"{i}. {h}" for i, h in enumerate(headlines))
    )
    try:
        resp = quick_llm.invoke(prompt).content
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.strip(), flags=re.M)
        data = json.loads(cleaned)
        result = [0.0] * len(headlines)
        for entry in data:
            idx = int(entry.get("idx", -1))
            score = float(entry.get("score", 0.0))
            if 0 <= idx < len(headlines):
                result[idx] = max(-1.0, min(1.0, score))
        return result
    except Exception:
        return [0.0] * len(headlines)


def score_sentiment(
    categorized: list[CategorizedNewsItem], quick_llm, batch_size: int = 10,
) -> list[CategorizedNewsItem]:
    """In-place style: 각 item에 sentiment_score 채워서 반환."""
    if not categorized or quick_llm is None:
        return categorized
    headlines = [c.item.headline for c in categorized]
    scores: list[float] = []
    for start in range(0, len(headlines), batch_size):
        batch = headlines[start:start + batch_size]
        scores.extend(_llm_score_batch(quick_llm, batch))
    out: list[CategorizedNewsItem] = []
    for c, s in zip(categorized, scores):
        out.append(c.model_copy(update={"sentiment_score": s}))
    return out


@register_skill(name="compute_news_sentiment_snapshot", category="news")
def compute_news_sentiment_snapshot(
    categorized: list[CategorizedNewsItem], as_of: date,
) -> NewsSentimentSnapshot:
    """Aggregate categorized news into a single Tier-3 snapshot."""
    if not categorized:
        return NewsSentimentSnapshot(
            counts={}, avg_sentiment={}, dominant_category=None,
            sentiment_dispersion=0.0, top_headline_per_category={},
            count_change_vs_7d={}, rising_category=None,
            source_date=as_of,
        )

    as_of_dt = datetime.combine(as_of, datetime.min.time())
    cutoff_24h = as_of_dt - timedelta(hours=24)
    cutoff_7d = as_of_dt - timedelta(days=7)

    def _ts(x):
        return x.replace(tzinfo=None) if x.tzinfo else x

    counts: dict[NewsCategory, int] = {}
    sent_by_cat: dict[NewsCategory, list[float]] = {}
    top_per_cat: dict[NewsCategory, tuple[str, float]] = {}  # (headline, abs_score)
    counts_24h: dict[NewsCategory, int] = {}
    counts_prev7d: dict[NewsCategory, int] = {}

    for c in categorized:
        cat = c.category
        score = c.sentiment_score
        counts[cat] = counts.get(cat, 0) + 1
        sent_by_cat.setdefault(cat, []).append(score)
        prev = top_per_cat.get(cat)
        if prev is None or abs(score) > prev[1]:
            top_per_cat[cat] = (c.item.headline[:120], abs(score))
        pub = _ts(c.item.published_at)
        if pub >= cutoff_24h:
            counts_24h[cat] = counts_24h.get(cat, 0) + 1
        elif pub >= cutoff_7d:
            counts_prev7d[cat] = counts_prev7d.get(cat, 0) + 1

    avg_sent = {cat: float(mean(scores)) for cat, scores in sent_by_cat.items()}
    dominant = max(counts, key=counts.get) if counts else None
    if len(avg_sent) >= 2:
        dispersion = float(stdev(avg_sent.values()))
    else:
        dispersion = 0.0

    top_headline_per_cat = {cat: h for cat, (h, _) in top_per_cat.items()}

    # Momentum: 24h count vs 직전 7일 일평균
    change: dict[NewsCategory, float] = {}
    rising: NewsCategory | None = None
    for cat in counts:
        recent = counts_24h.get(cat, 0)
        prev = counts_prev7d.get(cat, 0)
        prev_daily_avg = prev / 7.0
        delta = recent - prev_daily_avg
        change[cat] = round(delta, 2)
        if prev_daily_avg > 0 and recent >= prev_daily_avg * 2 and recent >= 2:
            if rising is None or recent > counts_24h.get(rising, 0):
                rising = cat

    return NewsSentimentSnapshot(
        counts=counts, avg_sentiment=avg_sent,
        dominant_category=dominant, sentiment_dispersion=dispersion,
        top_headline_per_category=top_headline_per_cat,
        count_change_vs_7d=change, rising_category=rising,
        source_date=as_of,
    )
