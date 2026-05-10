from datetime import datetime
from difflib import SequenceMatcher

from tradingagents.schemas.news import NewsItem, ImpactAssessment, RankedNews
from tradingagents.skills.registry import register_skill


_STRING_SIMILARITY_THRESHOLD = 0.85


def _are_same_event(
    a_item: NewsItem, a_impact: ImpactAssessment,
    b_item: NewsItem, b_impact: ImpactAssessment,
) -> bool:
    """Two news items represent the same event iff:
        (1) headline similarity > threshold AND
        (2) impact direction matches AND
        (3) impact asset classes overlap (Jaccard ≥ 0.5)

    Direction mismatch (e.g., 'rates cut' vs 'rates hike') → NOT duplicates,
    even if string similarity is 99%.
    """
    if SequenceMatcher(None, a_item.headline, b_item.headline).ratio() < _STRING_SIMILARITY_THRESHOLD:
        return False
    if a_impact.direction != b_impact.direction:
        return False
    a_set = set(a_impact.asset_classes_affected)
    b_set = set(b_impact.asset_classes_affected)
    if not a_set or not b_set:
        return False
    jaccard = len(a_set & b_set) / len(a_set | b_set)
    return jaccard >= 0.5


@register_skill(name="dedupe_rank_news", category="news")
def dedupe_rank_news(
    items: list[NewsItem],
    impacts: dict[str, ImpactAssessment],
    top_n: int = 10,
) -> list[RankedNews]:
    """Dedupe by direction-aware similarity, then rank by severity * recency.

    impacts: dict keyed by headline. Items without an impact are skipped.
    """
    paired: list[tuple[NewsItem, ImpactAssessment]] = [
        (item, impacts[item.headline])
        for item in items
        if item.headline in impacts
    ]

    deduped: list[tuple[NewsItem, ImpactAssessment]] = []
    for item, impact in paired:
        is_dup = any(
            _are_same_event(item, impact, prev_item, prev_impact)
            for prev_item, prev_impact in deduped
        )
        if not is_dup:
            deduped.append((item, impact))

    now = datetime.utcnow()
    ranked: list[RankedNews] = []
    for item, impact in deduped:
        recency = max(0.0, 1.0 - (now - item.published_at).total_seconds() / (7 * 86400))
        score = impact.severity * (0.5 + 0.5 * recency)
        ranked.append(RankedNews(item=item, impact=impact, rank_score=score))

    ranked.sort(key=lambda r: r.rank_score, reverse=True)
    return ranked[:top_n]
