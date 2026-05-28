"""Tier 2 — Article body fetcher + LLM summarizer + disk cache.

2026-05-28 신규 추가. RSS feed 의 description 만으로 부족한 경우 article 본문
fetch + LLM 요약. Top-N ranked news 만 처리 (cost 절감).

Backtest 제약:
- Historical URL link rot — 과거 article 본문 fetch 안 됨
- 따라서 *production-only* 모듈
- Cache 가 있으면 historical body_summary 복원 가능 (cache 가 backtest 친화적)

기술적 한계:
- Paywall (NYT/FT/WSJ): graceful None 반환
- JS-rendered (일부 한국 언론): static HTML 만 처리, JS 본문 없으면 skip
- Encoding: BeautifulSoup 자동 detect (chardet)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------- Constants ----------
_CACHE_DIR = Path.home() / ".tradingagents" / "cache" / "news_body"
_CACHE_TTL_DAYS = 7
_REQUEST_TIMEOUT = 10
_MAX_BODY_CHARS = 8000          # body fetch 후 LLM 호출 전 truncate
_SUMMARY_MAX_CHARS = 500        # LLM 요약 결과 max length
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _cache_path(url: str) -> Path:
    return _CACHE_DIR / f"{_cache_key(url)}.json"


def _read_cache(url: str) -> str | None:
    """Cache hit → return body_summary. Miss / TTL expired → None."""
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = datetime.fromisoformat(data["cached_at"])
        if datetime.utcnow() - cached_at > timedelta(days=_CACHE_TTL_DAYS):
            return None
        return data.get("body_summary")
    except Exception as e:
        logger.debug("cache read failed %s: %s", url, e)
        return None


def _write_cache(url: str, body_summary: str | None) -> None:
    """Write body_summary (or None for negative cache)."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url)
    try:
        path.write_text(
            json.dumps({
                "url": url,
                "body_summary": body_summary,
                "cached_at": datetime.utcnow().isoformat(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.debug("cache write failed %s: %s", url, e)


# ---------- Body fetching ----------


def _fetch_html(url: str) -> str | None:
    """HTTP GET + return text (or None on failure).

    Paywall (HTTP 403/451 등) 또는 timeout → None.
    """
    try:
        import requests
    except ImportError:
        logger.warning("requests not installed — body fetch disabled")
        return None
    try:
        r = requests.get(
            url, headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT, allow_redirects=True,
        )
        if r.status_code != 200:
            logger.debug("body fetch %s: HTTP %d", url, r.status_code)
            return None
        # Encoding auto-detect
        r.encoding = r.encoding if r.encoding != "ISO-8859-1" else r.apparent_encoding
        return r.text
    except Exception as e:
        logger.debug("body fetch %s failed: %s", url, e)
        return None


def _extract_article_body(html: str) -> str | None:
    """Extract article body via BeautifulSoup (multiple selectors fallback).

    가장 흔한 article container:
      <article>, <main>, [role="article"], .article-content, .news-article 등
    fallback: <p> tag 합산 (보통 article 본문이 <p> 다수).
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed — body extraction disabled")
        return None
    try:
        soup = BeautifulSoup(html, "html.parser")
        # 1차: 명시적 article container
        for selector in ["article", "main", "[role='article']",
                         ".article-content", ".news-article",
                         ".article_body", ".article-body",
                         "#articleBody", ".view_text"]:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(separator=" ", strip=True)
                if len(text) > 200:
                    return text[:_MAX_BODY_CHARS]
        # 2차: <p> tag 다수 합산
        paragraphs = soup.find_all("p")
        if len(paragraphs) >= 3:
            text = " ".join(p.get_text(strip=True) for p in paragraphs)
            if len(text) > 200:
                return text[:_MAX_BODY_CHARS]
        return None
    except Exception as e:
        logger.debug("body extraction failed: %s", e)
        return None


# ---------- LLM summarization ----------


def _summarize_body(quick_llm, body: str, headline: str) -> str | None:
    """LLM body 요약 (≤500자 한국어).

    Fail → None.
    """
    if quick_llm is None or not body:
        return None
    prompt = (
        f"Summarize this article body in ≤{_SUMMARY_MAX_CHARS} Korean characters. "
        f"Focus on (1) the core fact, (2) any *qualifying nuance* the headline misses "
        f"(e.g., 'limited scope', 'one-time event', 'expected vs surprise'), "
        f"(3) impact magnitude indicators. No prose padding.\n\n"
        f"Headline: \"{headline[:200]}\"\n\n"
        f"Body:\n{body[:_MAX_BODY_CHARS]}"
    )
    try:
        resp = quick_llm.invoke(prompt).content.strip()
        # markdown fence 제거
        resp = re.sub(r"^```(?:[a-z]+)?\s*|\s*```$", "", resp, flags=re.M)
        return resp[:_SUMMARY_MAX_CHARS]
    except Exception as e:
        logger.debug("body summarize failed: %s", e)
        return None


# ---------- Public API ----------


def fetch_and_summarize_body(url: str, headline: str, quick_llm) -> str | None:
    """End-to-end: cache check → fetch → extract → LLM summarize → cache write.

    Returns: body_summary (≤500자) or None on any failure.
    """
    if not url:
        return None
    # 1. Cache check
    cached = _read_cache(url)
    if cached is not None:
        logger.debug("body cache hit: %s", url[:60])
        return cached
    # Negative cache (이전 fetch 실패) 도 확인 — cached_path 존재하면 skip
    if _cache_path(url).exists():
        # write_cache 로 None 도 write 했으면 negative cache hit
        try:
            data = json.loads(_cache_path(url).read_text())
            if data.get("body_summary") is None:
                cached_at = datetime.fromisoformat(data["cached_at"])
                if datetime.utcnow() - cached_at < timedelta(days=_CACHE_TTL_DAYS):
                    return None  # 7d 안의 negative cache
        except Exception:
            pass
    # 2. HTTP fetch
    html = _fetch_html(url)
    if html is None:
        _write_cache(url, None)
        return None
    # 3. Body extract
    body = _extract_article_body(html)
    if body is None:
        _write_cache(url, None)
        return None
    # 4. LLM summarize
    summary = _summarize_body(quick_llm, body, headline)
    _write_cache(url, summary)
    return summary


def fetch_bodies_for_ranked(
    ranked_news, quick_llm, top_n: int = 10,
) -> dict[str, str | None]:
    """Top N ranked news 의 body_summary 일괄 fetch.

    Returns: {url: body_summary or None}
    """
    results: dict[str, str | None] = {}
    for r in ranked_news[:top_n]:
        item = r.item if hasattr(r, "item") else r
        url = item.url
        if not url:
            continue
        summary = fetch_and_summarize_body(url, item.headline, quick_llm)
        results[url] = summary
    return results
