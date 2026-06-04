from langchain_core.messages import AIMessage
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher


class _FakeLLM:
    def __init__(self, content):
        self._c = content
    def invoke(self, prompt):
        return AIMessage(content=self._c)


def _state():
    return {
        "macro_summary": "성장 둔화 신호 약함, 디스인플레 진행",
        "risk_summary": "systemic 3/10, risk-on",
        "technical_summary": "코스피 모멘텀 +",
        "news_summary": "반도체 업황 개선 뉴스",
    }


def test_bull_returns_markdown_view():
    node = create_bull_researcher(_FakeLLM("강세 논리: 위험자산 비중 확대"))
    out = node(_state())
    assert "bull_view" in out
    assert "강세" in out["bull_view"]


def test_bull_handles_missing_summaries():
    node = create_bull_researcher(_FakeLLM("ok"))
    out = node({})   # empty state — 빈 summary 로도 안 죽음
    assert isinstance(out["bull_view"], str)
