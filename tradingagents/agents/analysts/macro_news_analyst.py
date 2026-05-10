"""Macro News Analyst — calendar + news + impact classifier + ranker."""
from datetime import date

from tradingagents.schemas.reports import NewsReport
from tradingagents.skills.news.event_calendar import fetch_event_calendar_skill
from tradingagents.skills.news.impact_classifier import classify_event_impact
from tradingagents.skills.news.news_fetcher import fetch_macro_news_skill
from tradingagents.skills.news.ranker import dedupe_rank_news


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

        narrative = quick_llm.invoke(
            f"Summarize macro news in ≤500 Korean chars. "
            f"Top: {[r.item.headline[:50] for r in ranked[:3]]}"
        ).content[:500]
        top_headline = ranked[0].item.headline[:80] if ranked else "(none)"
        top_severity = ranked[0].impact.severity if ranked else "n/a"
        summary = (
            f"## News\nUpcoming events: {len(events)}\n"
            f"Top headlines (severity {top_severity}): {top_headline}\n"
        )[:2000]

        report = NewsReport(
            upcoming_events=events, ranked_news=ranked,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"news_report": report, "news_summary": summary}

    return node
