"""Macro News Analyst — calendar + news + impact classifier + ranker + Tier-1~5."""
from datetime import date

from tradingagents.schemas.reports import NewsReport
from tradingagents.skills.news.event_calendar import fetch_event_calendar_skill
from tradingagents.skills.news.categorizer import categorize_news
from tradingagents.skills.news.global_overnight import (
    compute_global_overnight_snapshot,
)
from tradingagents.skills.news.impact_classifier import classify_event_impact
from tradingagents.skills.news.news_fetcher import fetch_macro_news_skill
from tradingagents.skills.news.news_sentiment import (
    compute_news_sentiment_snapshot, score_sentiment,
)
from tradingagents.skills.news.ranker import dedupe_rank_news
from tradingagents.skills.news.release_surprise import (
    compute_release_surprise_snapshot,
)


def _summarize_overnight(snap) -> str:
    """Tier-1 압축: regime + seed + 카운트 (≤300자)."""
    if snap is None:
        return ""
    return (
        f"Tier-1 (global overnight, n={snap.fetched_count}/9):\n"
        f"  Regime: {snap.risk_regime_overnight}\n"
        f"  {snap.narrative_seed}\n"
    )


def _summarize_sentiment(snap) -> str:
    """Tier-3 압축: 카테고리별 count·sentiment + rising + top headline."""
    if snap is None or not snap.counts:
        return ""
    counts_str = ", ".join(f"{cat} {n}" for cat, n in snap.counts.items())
    sent_str = ", ".join(
        f"{cat} {s:+.2f}" for cat, s in snap.avg_sentiment.items()
    )
    rising = snap.rising_category or "(none)"
    top_lines = [
        f"    {cat}: {h[:80]}"
        for cat, h in list(snap.top_headline_per_category.items())[:3]
    ]
    return (
        f"Tier-3 (news sentiment, n={sum(snap.counts.values())}):\n"
        f"  Counts: {counts_str}\n"
        f"  Avg sentiment: {sent_str}\n"
        f"  Dominant: {snap.dominant_category}, Rising: {rising}\n"
        f"  Dispersion: {snap.sentiment_dispersion:.2f}\n"
        f"  Top per category:\n" + "\n".join(top_lines) + "\n"
    )


def _summarize_surprise(snap) -> str:
    """Tier-2 압축: 오늘 ★★★ + 30d bias + ESI."""
    if snap is None:
        return ""
    if not snap.today_releases and not snap.last_5d_releases:
        return f"Tier-2 (release surprise): no releases (waiting on SAVE/calendar data)\n"
    today_str = "; ".join(
        f"{r.indicator}({r.actual} vs {r.forecast}, {r.direction})"
        for r in snap.today_releases[:3]
    )
    return (
        f"Tier-2 (release surprise):\n"
        f"  Today high-importance: {snap.high_importance_today}\n"
        f"  Today releases: {today_str or '(none)'}\n"
        f"  30d ESI: {snap.surprise_index_30d:+.2f}, bias: {snap.bias_30d}\n"
    )


def create_macro_news_analyst(quick_llm, deep_llm):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])

        events = fetch_event_calendar_skill(as_of, days=90)
        items = fetch_macro_news_skill(window_days=7)

        # Classify impact for each (cap at 30 to control cost)
        impacts = {}
        for item in items[:30]:
            try:
                impact = classify_event_impact(
                    quick_llm, deep_llm,
                    headline=item.headline,
                    source=item.source,
                    date=item.published_at.isoformat(),
                )
                impacts[item.headline] = impact
            except Exception:
                continue

        ranked = dedupe_rank_news(items, impacts, top_n=10)

        # Tier-1: Global overnight snapshot (US 제외)
        try:
            overnight = compute_global_overnight_snapshot(as_of)
        except Exception:
            overnight = None
        overnight_summary = _summarize_overnight(overnight)

        # Tier-2: Release surprise — releases는 Tier-5 SAVE 또는 state에서 주입
        # 현재 단계에선 빈 list로 호출, 향후 SaveBriefSnapshot.economic_releases
        # 가 채워지면 자동으로 의미있는 값이 나옴.
        external_releases = state.get("release_surprises_30d", []) or []
        try:
            surprise_snapshot = compute_release_surprise_snapshot(
                external_releases, as_of=as_of,
            )
        except Exception:
            surprise_snapshot = None
        surprise_summary = _summarize_surprise(surprise_snapshot)

        # Tier-3: News categorizer + sentiment + momentum
        try:
            categorized = categorize_news(items, quick_llm=quick_llm)
            categorized = score_sentiment(categorized, quick_llm=quick_llm)
            sentiment_snapshot = compute_news_sentiment_snapshot(
                categorized, as_of=as_of,
            )
        except Exception:
            sentiment_snapshot = None
        sentiment_summary = _summarize_sentiment(sentiment_snapshot)

        narrative = quick_llm.invoke(
            f"Summarize macro news in ≤500 Korean chars. "
            f"Top: {[r.item.headline[:50] for r in ranked[:3]]}"
        ).content[:500]
        top_headline = ranked[0].item.headline[:80] if ranked else "(none)"
        top_severity = ranked[0].impact.severity if ranked else "n/a"
        summary = (
            f"## News\nUpcoming events: {len(events)}\n"
            f"Top headlines (severity {top_severity}): {top_headline}\n"
            f"{overnight_summary}"
            f"{surprise_summary}"
            f"{sentiment_summary}"
        )[:2000]

        report = NewsReport(
            upcoming_events=events, ranked_news=ranked,
            global_overnight=overnight,
            release_surprise=surprise_snapshot,
            news_sentiment=sentiment_snapshot,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"news_report": report, "news_summary": summary}

    return node
