"""Macro News Analyst — calendar + news + impact classifier + ranker + Tier-1~5."""
from datetime import date

from tradingagents.schemas.reports import NewsReport
from tradingagents.skills.news.event_calendar import fetch_event_calendar_skill
from tradingagents.skills.news.categorizer import categorize_news
from tradingagents.skills.news.cb_speaker_tracker import (
    compute_speaker_aggregate, extract_speaker_events,
)
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
from tradingagents.skills.news.save_ingestor import ingest_save_brief


def _summarize_overnight(snap) -> str:
    """Tier-1 압축: regime + seed + 카운트 (≤300자)."""
    if snap is None:
        return ""
    return (
        f"Tier-1 (global overnight, n={snap.fetched_count}/9):\n"
        f"  Regime: {snap.risk_regime_overnight}\n"
        f"  {snap.narrative_seed}\n"
    )


def _summarize_save(snap) -> str:
    """Tier-5 압축: SAVE 추출 카운트 + cross-channel 기여 명시."""
    if snap is None:
        return ""
    return (
        f"Tier-5 (SAVE brief {snap.brief_date}, pages {snap.pages_parsed}):\n"
        f"  Releases extracted: {len(snap.economic_releases)} (→ Tier-2)\n"
        f"  News cards extracted: {len(snap.news_cards)} (→ Tier-3 input)\n"
        f"  Weekly schedule: {len(snap.weekly_schedule)} (→ event_calendar 보강)\n"
    )


def _summarize_speakers(agg) -> str:
    """Tier-4 압축: Fed/BOK balance + voting + 최근 1-2 발언."""
    if agg is None:
        return ""
    n_fed = len(agg.fed_speakers_7d)
    n_bok = len(agg.bok_speakers_7d)
    n_other = len(agg.other_speakers_7d)
    if n_fed + n_bok + n_other == 0:
        return ""
    fed_recent = "; ".join(
        f"{e.speaker}({e.tone})" for e in agg.fed_speakers_7d[:3]
    ) or "(none)"
    bok_recent = "; ".join(
        f"{e.speaker}({e.tone})" for e in agg.bok_speakers_7d[:3]
    ) or "(none)"
    return (
        f"Tier-4 (CB speakers 7d, n={n_fed + n_bok + n_other}):\n"
        f"  Fed balance: {agg.fed_tone_balance:+.2f} "
        f"(voting only: {agg.fed_voting_balance:+.2f}, n={n_fed})\n"
        f"  BOK balance: {agg.bok_tone_balance:+.2f} (n={n_bok})\n"
        f"  Fed recent: {fed_recent}\n"
        f"  BOK recent: {bok_recent}\n"
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

        # Tier-5: SAVE 브리핑 ingest (가능 시) — Tier-2/3 input 보강에 우선 사용
        try:
            save_brief = ingest_save_brief(as_of=as_of, quick_llm=quick_llm)
        except Exception:
            save_brief = None
        save_summary = _summarize_save(save_brief)

        # Tier-2: Release surprise — SAVE에서 추출된 releases 우선, fallback은
        # state에 명시적으로 주입된 release_surprises_30d.
        external_releases = list(state.get("release_surprises_30d", []) or [])
        if save_brief and save_brief.economic_releases:
            external_releases = list(save_brief.economic_releases) + external_releases
        try:
            surprise_snapshot = compute_release_surprise_snapshot(
                external_releases, as_of=as_of,
            )
        except Exception:
            surprise_snapshot = None
        surprise_summary = _summarize_surprise(surprise_snapshot)

        # SAVE에서 추출된 news cards를 Tier-3 input items에 병합 (중복 제거는
        # categorizer 이후 단계에서 dedupe_rank가 처리)
        if save_brief and save_brief.news_cards:
            items = list(items) + list(save_brief.news_cards)

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

        # Tier-4: CB speaker tone tracker
        try:
            speaker_events = extract_speaker_events(items, quick_llm=quick_llm, as_of=as_of)
            speaker_aggregate = compute_speaker_aggregate(
                speaker_events, as_of=as_of,
            )
        except Exception:
            speaker_aggregate = None
        speaker_summary = _summarize_speakers(speaker_aggregate)

        narrative = quick_llm.invoke(
            f"Summarize macro news in ≤500 Korean chars. "
            f"Top: {[r.item.headline[:50] for r in ranked[:3]]}"
        ).content[:500]
        top_headline = ranked[0].item.headline[:80] if ranked else "(none)"
        top_severity = ranked[0].impact.severity if ranked else "n/a"
        # SAVE 주간 일정을 upcoming_events에 병합 (중복은 단순 dedupe)
        if save_brief and save_brief.weekly_schedule:
            existing = {(e.event_date, e.description) for e in events}
            for ev in save_brief.weekly_schedule:
                if (ev.event_date, ev.description) not in existing:
                    events.append(ev)

        summary = (
            f"## News\nUpcoming events: {len(events)}\n"
            f"Top headlines (severity {top_severity}): {top_headline}\n"
            f"{overnight_summary}"
            f"{surprise_summary}"
            f"{sentiment_summary}"
            f"{speaker_summary}"
            f"{save_summary}"
        )[:2000]

        report = NewsReport(
            upcoming_events=events, ranked_news=ranked,
            global_overnight=overnight,
            release_surprise=surprise_snapshot,
            news_sentiment=sentiment_snapshot,
            cb_speakers=speaker_aggregate,
            save_brief=save_brief,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"news_report": report, "news_summary": summary}

    return node
