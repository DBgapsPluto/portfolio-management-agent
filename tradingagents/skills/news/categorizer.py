"""Tier-3 — News categorizer (keyword 1차 + LLM 2차 fallback).

LLM 호출 최소화: 키워드 매칭으로 잡히는 80%는 cost 0. 나머지만 batch LLM.
"""
import json
import re
from typing import Literal

from tradingagents.schemas.news import (
    CategorizedNewsItem, NewsCategory, NewsItem,
)
from tradingagents.skills.registry import register_skill


KEYWORD_MAP: dict[NewsCategory, tuple[str, ...]] = {
    "policy": (
        "fomc", "fed", "ecb", "boj", "bok", "powell", "lagarde", "ueda",
        "rate cut", "rate hike", "tariff", "sanction", "regulation",
        "monetary", "fiscal", "tax", "budget", "subsidy",
        "연준", "금통위", "이창용", "기준금리", "규제", "관세",
        "재정", "긴축", "완화",
    ),
    "macro": (
        "cpi", "ppi", "gdp", "employment", "payroll", "nonfarm",
        "unemployment", "jobless", "retail sales", "ism", "pmi",
        "housing", "inventories", "import", "export",
        "물가", "고용", "취업", "산업생산", "소매판매", "수출",
        "수입", "경상수지", "gdp", "성장률",
    ),
    "corporate": (
        "earnings", "guidance", "revenue", "profit", "m&a", "merger",
        "acquisition", "buyback", "dividend", "ceo", "cfo", "lawsuit",
        "ipo", "spinoff",
        "실적", "합병", "인수", "배당", "자사주", "유상증자", "ipo",
        "ackman", "buffett",
    ),
    "geopolitical": (
        "war", "election", "russia", "ukraine", "china", "taiwan",
        "israel", "iran", "north korea", "trump", "biden", "putin",
        "xi jinping", "coup", "tension",
        "전쟁", "선거", "러시아", "우크라이나", "중국", "대만",
        "이스라엘", "이란", "북한",
    ),
    "market_commentary": (
        "target", "upgrade", "downgrade", "rating", "analyst",
        "goldman", "morgan stanley", "jpmorgan", "rbc", "wells fargo",
        "fund manager", "outlook", "forecast", "view",
        "목표가", "투자의견", "상향", "하향", "전망",
    ),
}


def _keyword_classify(text: str) -> tuple[NewsCategory | None, int]:
    """Return (category, hits) or (None, 0).

    2026-05-28 — Tier 1: text 가 headline + description 결합 string 일 수 있음.
    keyword 매칭 검색 범위가 늘어 정확도 향상.
    """
    lower = text.lower()
    best: NewsCategory | None = None
    best_hits = 0
    for cat, keywords in KEYWORD_MAP.items():
        hits = sum(1 for k in keywords if k in lower)
        if hits > best_hits:
            best_hits = hits
            best = cat
    return best, best_hits


def _format_for_classify(item: NewsItem) -> str:
    """Headline + (body_summary > description) 결합.

    2026-05-28 Tier 1 + Tier 2 우선순위:
    - body_summary 있으면 ≤500자 (가장 풍부, article 본문 LLM 요약)
    - description 있으면 ≤500자 (RSS feed 의 summary)
    - 둘 다 없으면 headline 만
    """
    if item.body_summary:
        return f"{item.headline} — {item.body_summary[:500]}"
    if item.description:
        return f"{item.headline} — {item.description[:500]}"
    return item.headline


def _llm_classify_batch(
    quick_llm, contexts: list[str],
) -> list[NewsCategory]:
    """LLM에게 batch 분류 의뢰. 2026-05-28 Tier 1: headline + description 받음."""
    if not contexts:
        return []
    prompt = (
        "You are a financial news classifier. Classify each news (headline + brief description) into "
        "exactly one of: policy, macro, corporate, geopolitical, "
        "market_commentary.\n\n"
        "Return ONLY a JSON array like "
        "[{\"idx\": 0, \"category\": \"policy\"}, ...]. "
        "No prose, no markdown.\n\nNews:\n"
        + "\n".join(f"{i}. {h}" for i, h in enumerate(contexts))
    )
    try:
        resp = quick_llm.invoke(prompt).content
        # strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", resp.strip(), flags=re.M)
        data = json.loads(cleaned)
        result: list[NewsCategory] = ["macro"] * len(contexts)
        valid = set(KEYWORD_MAP.keys())
        for entry in data:
            idx = int(entry.get("idx", -1))
            cat = entry.get("category", "macro")
            if 0 <= idx < len(contexts) and cat in valid:
                result[idx] = cat  # type: ignore[assignment]
        return result
    except Exception:
        return ["macro"] * len(contexts)


@register_skill(name="categorize_news", category="news")
def categorize_news(
    items: list[NewsItem], quick_llm=None, llm_batch_size: int = 10,
) -> list[CategorizedNewsItem]:
    """뉴스 list를 분류. quick_llm이 None이면 LLM fallback 생략."""
    out: list[CategorizedNewsItem] = []
    llm_pending: list[tuple[int, str]] = []  # (output_idx, headline)

    for item in items:
        # 2026-05-28 Tier 1: keyword 매칭에 description 도 포함 (검색 범위 ↑)
        ctx = _format_for_classify(item)
        cat, hits = _keyword_classify(ctx)
        if cat is not None and hits >= 1:
            out.append(CategorizedNewsItem(
                item=item, category=cat,
                sentiment_score=0.0,
                classifier_source="keyword",
            ))
        else:
            # placeholder, LLM이 채울 예정
            out.append(CategorizedNewsItem(
                item=item, category="macro",  # default
                sentiment_score=0.0,
                classifier_source="llm",
            ))
            llm_pending.append((len(out) - 1, ctx))

    if quick_llm is not None and llm_pending:
        for start in range(0, len(llm_pending), llm_batch_size):
            batch = llm_pending[start:start + llm_batch_size]
            contexts = [c for _, c in batch]
            cats = _llm_classify_batch(quick_llm, contexts)
            for (out_idx, _), cat in zip(batch, cats):
                out[out_idx] = out[out_idx].model_copy(update={"category": cat})

    return out
