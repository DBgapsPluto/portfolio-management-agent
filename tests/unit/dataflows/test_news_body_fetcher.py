"""Unit tests for Tier 2 news body fetcher (2026-05-28)."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.dataflows import news_body_fetcher as nbf


def test_extract_article_body_article_tag():
    """<article> tag 안의 text 추출."""
    html = """
    <html><body>
      <header>nav</header>
      <article>
        <h1>Headline</h1>
        <p>This is the first paragraph of the article body, which is long enough.</p>
        <p>Second paragraph with more context about the actual content of the news.</p>
        <p>Third paragraph to ensure we have substantial body content for analysis.</p>
      </article>
      <footer>copyright</footer>
    </body></html>
    """
    body = nbf._extract_article_body(html)
    assert body is not None
    assert "first paragraph" in body
    assert "Third paragraph" in body
    # nav/footer 제외 확인
    assert "copyright" not in body
    assert "nav" not in body[:50]


def test_extract_article_body_fallback_p_tags():
    """명시 article container 없으면 <p> tag 다수로 fallback (>200자)."""
    html = """
    <html><body>
      <div class="random">
        <p>Paragraph one with substantially meaningful content that contains useful narrative details about the topic at hand here.</p>
        <p>Paragraph two also brings additional context and elaborates on key points that support the central thesis discussed.</p>
        <p>Paragraph three concludes with a synthesis of the prior arguments and offers a forward-looking perspective.</p>
      </div>
    </body></html>
    """
    body = nbf._extract_article_body(html)
    assert body is not None
    assert "Paragraph one" in body
    assert "Paragraph three" in body


def test_extract_article_body_too_short():
    """너무 짧으면 None."""
    html = "<html><body><p>Tiny</p></body></html>"
    body = nbf._extract_article_body(html)
    assert body is None


def test_cache_write_read_roundtrip(tmp_path, monkeypatch):
    """cache write 후 read 동일 내용."""
    monkeypatch.setattr(nbf, "_CACHE_DIR", tmp_path)
    url = "https://example.com/news/123"
    nbf._write_cache(url, "summary content here")
    cached = nbf._read_cache(url)
    assert cached == "summary content here"


def test_cache_negative_returns_none_within_ttl(tmp_path, monkeypatch):
    """None body_summary (negative cache) 도 저장. _read_cache 는 None 반환 (구분 안 함).

    fetch_and_summarize_body 의 negative cache 분기는 별도 path 로 처리.
    """
    monkeypatch.setattr(nbf, "_CACHE_DIR", tmp_path)
    url = "https://example.com/paywall/article"
    nbf._write_cache(url, None)
    # _read_cache 는 body_summary 가 None 이면 그 None 반환
    cached = nbf._read_cache(url)
    assert cached is None


def test_cache_ttl_expired(tmp_path, monkeypatch):
    """TTL 지나면 None (cache miss)."""
    monkeypatch.setattr(nbf, "_CACHE_DIR", tmp_path)
    url = "https://example.com/old"
    # 직접 expired cache write
    expired_at = datetime.utcnow() - timedelta(days=10)
    path = nbf._cache_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "url": url, "body_summary": "old",
        "cached_at": expired_at.isoformat(),
    }))
    cached = nbf._read_cache(url)
    assert cached is None


def test_summarize_body_uses_llm(monkeypatch):
    """LLM mock 으로 호출 검증 + 결과 reflection."""
    quick_llm = MagicMock()
    quick_llm.invoke.return_value.content = "한국어 요약 결과"
    result = nbf._summarize_body(quick_llm, "long body text here" * 50, "headline")
    assert result == "한국어 요약 결과"
    quick_llm.invoke.assert_called_once()
    # prompt 가 body + headline 포함
    call_arg = quick_llm.invoke.call_args[0][0]
    assert "headline" in call_arg
    assert "long body" in call_arg


def test_fetch_and_summarize_cache_hit(tmp_path, monkeypatch):
    """Cache hit 시 HTTP fetch 안 함."""
    monkeypatch.setattr(nbf, "_CACHE_DIR", tmp_path)
    url = "https://example.com/cached"
    nbf._write_cache(url, "cached summary")
    quick_llm = MagicMock()
    # _fetch_html 이 호출되지 않아야 함
    with patch.object(nbf, "_fetch_html") as mock_fetch:
        result = nbf.fetch_and_summarize_body(url, "headline", quick_llm)
        assert result == "cached summary"
        mock_fetch.assert_not_called()
        quick_llm.invoke.assert_not_called()


def test_fetch_and_summarize_empty_url():
    """빈 URL → None."""
    assert nbf.fetch_and_summarize_body("", "h", None) is None


def test_fetch_and_summarize_http_fail(tmp_path, monkeypatch):
    """HTTP fetch 실패 → negative cache write + None 반환."""
    monkeypatch.setattr(nbf, "_CACHE_DIR", tmp_path)
    url = "https://example.com/notexist"
    with patch.object(nbf, "_fetch_html", return_value=None):
        result = nbf.fetch_and_summarize_body(url, "h", MagicMock())
        assert result is None
    # negative cache 작성 확인
    assert nbf._cache_path(url).exists()


def test_fetch_bodies_for_ranked_dispatches(tmp_path, monkeypatch):
    """fetch_bodies_for_ranked 가 top_n 만큼 호출."""
    monkeypatch.setattr(nbf, "_CACHE_DIR", tmp_path)
    # mock ranked news (item.url, item.headline 만 필요)
    class MockItem:
        def __init__(self, url, headline):
            self.url, self.headline = url, headline
    class MockRanked:
        def __init__(self, item): self.item = item
    ranked = [MockRanked(MockItem(f"https://x.com/{i}", f"h{i}")) for i in range(5)]
    quick_llm = MagicMock()
    with patch.object(nbf, "fetch_and_summarize_body") as mock_fs:
        mock_fs.return_value = "summary"
        results = nbf.fetch_bodies_for_ranked(ranked, quick_llm, top_n=3)
    assert len(results) == 3
    assert mock_fs.call_count == 3
