"""Macro News Analyst — calendar + news + impact classifier + ranker + Tier-1~5."""
import logging
from datetime import date

logger = logging.getLogger(__name__)

# Stage 1 audit (2026-05-26, Task 4): named constants.
EVENT_CALENDAR_LOOKAHEAD_DAYS: int = 90
NEWS_WINDOW_DAYS: int = 7
IMPACT_CLASSIFY_CAP: int = 30   # cost 보호 — LLM 호출당 ~$0.01 가정 시 $0.30/run.
TOP_RANKED_N: int = 10
NARRATIVE_MAX_CHARS: int = 500
# 2026-05-28 Tier 2: top N ranked news 의 article body fetch + LLM summary.
# cache hit 면 추가 cost X. cache miss 면 HTTP + LLM 1 호출/news.
BODY_FETCH_TOP_N: int = 10
SUMMARY_MAX_CHARS: int = 2000

from tradingagents.schemas.reports import NewsReport
from tradingagents.skills.news.event_calendar import fetch_event_calendar_skill
from tradingagents.skills.news.categorizer import categorize_news, prioritize_macro_relevant
from tradingagents.skills.news.cb_speaker_tracker import (
    compute_speaker_aggregate, extract_speaker_events,
)
from tradingagents.skills.news.global_overnight import (
    compute_global_overnight_snapshot,
)
from tradingagents.dataflows.news_body_fetcher import fetch_bodies_for_ranked
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
    # 섹터/투자 테마 지형 (category 와 직교 축) — count 내림차순, 상위 3개 대표
    # 헤드라인. 테마 없으면 블록 생략 (잡음 방지).
    theme_block = ""
    if snap.theme_counts:
        ranked_themes = sorted(snap.theme_counts.items(), key=lambda x: -x[1])
        theme_str = ", ".join(f"{th} {n}" for th, n in ranked_themes)
        theme_top_lines = [
            f"    {th}: {snap.theme_top_headline.get(th, '')[:80]}"
            for th, _ in ranked_themes[:3]
            if snap.theme_top_headline.get(th)
        ]
        theme_block = (
            f"  Themes: {theme_str}\n"
            + ("  Top per theme:\n" + "\n".join(theme_top_lines) + "\n"
               if theme_top_lines else "")
        )
    return (
        f"Tier-3 (news sentiment, n={sum(snap.counts.values())}):\n"
        f"  Counts: {counts_str}\n"
        f"  Avg sentiment: {sent_str}\n"
        f"  Dominant: {snap.dominant_category}, Rising: {rising}\n"
        f"  Dispersion: {snap.sentiment_dispersion:.2f}\n"
        f"  Top per category:\n" + "\n".join(top_lines) + "\n"
        + theme_block
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
        logger.info("macro_news start: as_of=%s", as_of)

        events = fetch_event_calendar_skill(as_of, days=EVENT_CALENDAR_LOOKAHEAD_DAYS)
        items = fetch_macro_news_skill(window_days=NEWS_WINDOW_DAYS, as_of=as_of)
        # 거시·지정학 뉴스가 종목 헤드라인 볼륨에 밀려 impact-classify cap 밖으로
        # 잘리지 않도록 budget 앞쪽으로 우선 배치 (cost 0).
        items = prioritize_macro_relevant(items)
        logger.info(
            "macro_news: %d events + %d news items fetched", len(events), len(items),
        )

        # Classify impact for each (cap at IMPACT_CLASSIFY_CAP to control cost).
        impacts = {}
        impact_failures = 0
        for item in items[:IMPACT_CLASSIFY_CAP]:
            try:
                # 2026-05-28 Tier 1: description (RSS summary) 도 LLM 에 전달.
                # description 있으면 prompt 의 {description_block} 채움. None 이면 빈 string.
                desc_block = (
                    f'Description: "{item.description[:500]}"\n'
                    if item.description else ""
                )
                impact = classify_event_impact(
                    quick_llm, deep_llm,
                    headline=item.headline,
                    description_block=desc_block,
                    source=item.source,
                    date=item.published_at.isoformat(),
                )
                impacts[item.headline] = impact
            except Exception as e:
                impact_failures += 1
                logger.debug("classify_event_impact failed for headline: %s", e)
                continue
        if impact_failures > 0:
            logger.warning(
                "macro_news: %d/%d impact classifications failed",
                impact_failures, min(len(items), IMPACT_CLASSIFY_CAP),
            )

        ranked = dedupe_rank_news(items, impacts, top_n=TOP_RANKED_N, as_of=as_of)

        # 2026-05-28 Tier 2: top N ranked news 의 article body fetch + LLM summary.
        # Cache hit (TTL 7d) 면 추가 cost 0. Paywall/timeout 은 graceful None.
        # 결과를 item.body_summary 에 채워 downstream (sentiment / categorize / narrative)
        # 가 활용. Top ranked 만 처리 (cost: top 10 × 1 LLM/news cache miss 시).
        try:
            body_summaries = fetch_bodies_for_ranked(
                ranked, quick_llm, top_n=BODY_FETCH_TOP_N,
            )
            # ranked 의 각 item 에 body_summary 채움 (model_copy)
            url_to_summary = body_summaries
            new_ranked = []
            for r in ranked:
                summary = url_to_summary.get(r.item.url)
                if summary:
                    new_item = r.item.model_copy(update={"body_summary": summary})
                    new_ranked.append(r.model_copy(update={"item": new_item}))
                else:
                    new_ranked.append(r)
            ranked = new_ranked
            n_with_body = sum(1 for r in ranked if r.item.body_summary)
            logger.info(
                "macro_news: Tier 2 body summaries — %d/%d ranked news",
                n_with_body, len(ranked),
            )
        except Exception as e:
            logger.warning("Tier 2 body fetch failed (graceful skip): %s", e)

        # Tier-1: Global overnight snapshot (US 제외)
        try:
            overnight = compute_global_overnight_snapshot(as_of)
        except Exception as e:
            logger.warning("overnight snapshot failed → None: %s", e)
            overnight = None
        overnight_summary = _summarize_overnight(overnight)

        # Tier-5: SAVE 브리핑 ingest (가능 시) — Tier-2/3 input 보강에 우선 사용
        try:
            save_brief = ingest_save_brief(as_of=as_of, quick_llm=quick_llm)
        except Exception as e:
            logger.warning("SAVE brief ingest failed → None: %s", e)
            save_brief = None
        save_summary = _summarize_save(save_brief)

        # Tier-2: Release surprise — SAVE에서 추출된 releases 우선, fallback은
        # state에 명시적으로 주입된 release_surprises_30d.
        external_releases = list(state.get("release_surprises_30d", []) or [])
        if save_brief and save_brief.economic_releases:
            external_releases = list(save_brief.economic_releases) + external_releases
        else:
            logger.info(
                "macro_news: SAVE brief releases unavailable, using state fallback "
                "release_surprises_30d=%d items", len(external_releases),
            )
        try:
            surprise_snapshot = compute_release_surprise_snapshot(
                external_releases, as_of=as_of,
            )
        except Exception as e:
            logger.warning("release_surprise compute failed → None: %s", e)
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
        except Exception as e:
            logger.warning("news sentiment pipeline failed → None: %s", e)
            sentiment_snapshot = None
        sentiment_summary = _summarize_sentiment(sentiment_snapshot)

        # Tier-4: CB speaker tone tracker
        try:
            speaker_events = extract_speaker_events(items, quick_llm=quick_llm, as_of=as_of)
            speaker_aggregate = compute_speaker_aggregate(
                speaker_events, as_of=as_of,
            )
        except Exception as e:
            logger.warning("speaker tracker failed → None: %s", e)
            speaker_aggregate = None
        speaker_summary = _summarize_speakers(speaker_aggregate)

        # Missing-tier inventory — debug 가시화.
        _missing_inventory = {
            "overnight": overnight is None,
            "save_brief": save_brief is None,
            "release_surprise": surprise_snapshot is None,
            "news_sentiment": sentiment_snapshot is None,
            "cb_speaker": speaker_aggregate is None,
        }
        n_missing = sum(_missing_inventory.values())
        if n_missing > 0:
            missing_names = [k for k, v in _missing_inventory.items() if v]
            logger.warning(
                "macro_news: %d/%d tiers missing: %s",
                n_missing, len(_missing_inventory), missing_names,
            )

        # 2026-05-28 Tier 1 + Tier 2: top 3 news 의 body_summary > description > headline 우선순위.
        # Tier 2 의 body_summary 가 있으면 가장 풍부한 context (article 본문 LLM 요약).
        # 없으면 Tier 1 의 description (RSS), 둘 다 없으면 headline 만.
        top3_context = []
        for r in ranked[:3]:
            line = f"- {r.item.headline[:80]}"
            if r.item.body_summary:
                line += f" — [BODY] {r.item.body_summary[:300]}"
            elif r.item.description:
                line += f" — [DESC] {r.item.description[:200]}"
            top3_context.append(line)
        narrative = quick_llm.invoke(
            f"Summarize macro news in ≤{NARRATIVE_MAX_CHARS} Korean chars. "
            f"Cite specific nuance from [BODY] / [DESC] when present. "
            f"Headline-only items: cite cautiously without overstating.\n\nTop news:\n"
            + "\n".join(top3_context)
        ).content[:NARRATIVE_MAX_CHARS]
        top_headline = ranked[0].item.headline[:80] if ranked else "(none)"
        top_severity = ranked[0].impact.severity if ranked else "n/a"
        # SAVE 주간 일정을 upcoming_events에 병합 (중복은 단순 dedupe)
        if save_brief and save_brief.weekly_schedule:
            existing = {(e.event_date, e.description) for e in events}
            for ev in save_brief.weekly_schedule:
                if (ev.event_date, ev.description) not in existing:
                    events.append(ev)

        missing_line = (
            f"Missing tiers: {n_missing}/{len(_missing_inventory)} "
            f"({', '.join(k for k, v in _missing_inventory.items() if v)})\n"
            if n_missing > 0 else ""
        )
        summary = (
            f"## News\n{missing_line}"
            f"Upcoming events: {len(events)}\n"
            f"Top headlines (severity {top_severity}): {top_headline}\n"
            f"{overnight_summary}"
            f"{surprise_summary}"
            f"{sentiment_summary}"
            f"{speaker_summary}"
            f"{save_summary}"
        )[:SUMMARY_MAX_CHARS]

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
