from pathlib import Path
from unittest.mock import MagicMock

from tradingagents.reports.philosophy import (
    generate_philosophy,
    write_philosophy,
    _build_state_summary,
)


def _make_state():
    wv = MagicMock()
    wv.method = MagicMock(value="hrp")
    wv.weights = {"A069500": 0.5, "A114800": 0.3, "A148070": 0.2}
    wv.rationale = "5-bucket target met"
    return {
        "macro_summary": "regime: recession",
        "risk_summary": "VIX 25",
        "technical_summary": "clusters",
        "news_summary": "events",
        "research_debate_summary": "60/40 풍선",
        "weight_vector": wv,
    }


def test_philosophy_min_length():
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "x" * 4500
    text = generate_philosophy(_make_state(), deep_llm)
    assert len(text) >= 4000


def test_philosophy_retries_when_short():
    """If first response < 4000 chars, generator retries once."""
    deep_llm = MagicMock()
    short = MagicMock(content="too short")
    long = MagicMock(content="y" * 4500)
    deep_llm.invoke.side_effect = [short, long]
    text = generate_philosophy(_make_state(), deep_llm)
    assert len(text) >= 4000
    assert deep_llm.invoke.call_count == 2


def test_write_philosophy_creates_file(tmp_path: Path):
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "z" * 4200
    out = tmp_path / "philosophy.md"
    result = write_philosophy(_make_state(), deep_llm, out)
    assert result == out
    assert out.read_text(encoding="utf-8").startswith("z")
    assert len(out.read_text(encoding="utf-8")) >= 4000


def test_build_state_summary_includes_fx_block():
    state = dict(_make_state())
    state["fx_exposure"] = {"USD": 0.55, "KRW": 0.35, "CNY": 0.10}
    summary = _build_state_summary(state)
    assert "FX(환) 노출" in summary
    assert "USD 55.0%" in summary


def test_build_state_summary_fx_absent_graceful():
    summary = _build_state_summary(_make_state())   # fx_exposure 없음
    assert "FX(환) 노출" in summary
    assert "(미산출)" in summary
