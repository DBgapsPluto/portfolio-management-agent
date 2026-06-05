"""Tier-3 — News categorizer (keyword 1차 + LLM 2차 fallback).

LLM 호출 최소화: 키워드 매칭으로 잡히는 80%는 cost 0. 나머지만 batch LLM.
"""
import json
import re
from typing import Literal

from tradingagents.schemas.news import (
    CategorizedNewsItem, NewsCategory, NewsItem, ThemeTag,
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


# 섹터/투자 테마 keyword (category와 직교). 한 텍스트가 여러 테마 매칭 가능.
# 짧은 토큰(' ev ')은 오탐 방지로 공백 포함. 'space' 단독은 SpaceX 인덱스 뉴스
# 오탐이 많아 'spacex'·'satellite' 등 구체 토큰만 사용.
THEME_KEYWORD_MAP: dict[ThemeTag, tuple[str, ...]] = {
    "ai_semis": (
        "ai ", "a.i.", "artificial intelligence", "chip", "semiconductor",
        "nvidia", "broadcom", "tsmc", "amd", "gpu", "openai", "anthropic",
        "data center", "데이터센터", "반도체", "인공지능", "엔비디아",
    ),
    "ev_battery": (
        "electric vehicle", " ev ", "ev,", "tesla", "rivian", "byd",
        "battery", "lithium", "배터리", "전기차", "이차전지", "2차전지",
    ),
    "energy": (
        "oil", "crude", "opec", "nuclear", "uranium", "solar", " lng",
        "natural gas", "pipeline", "유가", "원전", "에너지", "정유", "조선",
    ),
    "defense_space": (
        "defense", "defence", "weapon", "missile", "military", "spacex",
        "satellite", "drone", "방산", "무기",
    ),
    "biotech_health": (
        "biotech", "pharma", " drug", "fda", "vaccine", "obesity",
        "weight-loss", "clinical", "바이오", "제약",
    ),
    "crypto_fintech": (
        "bitcoin", "crypto", "ethereum", "stablecoin", "blockchain",
        "비트코인", "코인", "가상자산",
    ),
}


def _keyword_themes(text: str) -> set[ThemeTag]:
    """텍스트에서 섹터/투자 테마 태그 set 추출 (0개 이상). cost 0.

    category 와 달리 '단일 best'가 아니라 매칭되는 모든 테마를 반환 — 한 뉴스가
    여러 섹터를 동시에 다룰 수 있기 때문 (예: 'Tesla battery vs oil').
    """
    lower = text.lower()
    return {
        theme for theme, kws in THEME_KEYWORD_MAP.items()
        if any(k in lower for k in kws)
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
        # 테마는 category 와 독립 — keyword 로만 태깅 (cost 0, LLM 경로와 무관).
        themes = sorted(_keyword_themes(ctx))
        cat, hits = _keyword_classify(ctx)
        if cat is not None and hits >= 1:
            out.append(CategorizedNewsItem(
                item=item, category=cat,
                sentiment_score=0.0,
                classifier_source="keyword",
                themes=themes,
            ))
        else:
            # placeholder, LLM이 category 만 채울 예정 (themes 는 이미 확정)
            out.append(CategorizedNewsItem(
                item=item, category="macro",  # default
                sentiment_score=0.0,
                classifier_source="llm",
                themes=themes,
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


# impact-classify budget를 우선 배정할 거시·지정학 카테고리 (종목/시황 제외).
_MACRO_RELEVANT: frozenset[NewsCategory] = frozenset({"policy", "macro", "geopolitical"})


@register_skill(name="prioritize_macro_relevant", category="news")
def prioritize_macro_relevant(items: list[NewsItem]) -> list[NewsItem]:
    """거시·지정학·정책 뉴스를 list 앞쪽으로 stable 재배치 (cost 0, LLM 미사용).

    impact-classify는 앞 N건(IMPACT_CLASSIFY_CAP)만 LLM에 보내고 그 안에 든
    뉴스만 ranked_news/narrative로 stage2에 전달된다. 종목/실적 헤드라인이 feed
    앞자리를 채우면 진짜 거시 뉴스가 cap 밖으로 잘린다 (2026-06-05 실측: 지정학
    15건 중 cap 내 3건, 진짜 이란 뉴스는 위치 51 → 제외). keyword 분류로 거시·
    지정학 항목을 앞으로 옮겨 budget이 그쪽에 쓰이게 한다. severity 랭킹은 그
    다음 단계에서 적용되므로 키워드 오탐은 저-severity로 자연 탈락한다.
    """
    def _is_relevant(item: NewsItem) -> bool:
        cat, hits = _keyword_classify(_format_for_classify(item))
        return hits >= 1 and cat in _MACRO_RELEVANT

    # sorted는 stable → 동일 그룹 내 원래 순서 보존. 관련(0)이 비관련(1)보다 앞.
    return sorted(items, key=lambda it: 0 if _is_relevant(it) else 1)
