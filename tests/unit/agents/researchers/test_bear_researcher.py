from langchain_core.messages import AIMessage
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher


class _FakeLLM:
    def __init__(self, content):
        self._c = content
    def invoke(self, prompt):
        return AIMessage(content=self._c)


def test_bear_returns_markdown_view():
    node = create_bear_researcher(_FakeLLM("약세 논리: 안전자산 비중 확대"))
    out = node({"macro_summary": "x", "risk_summary": "y",
                "technical_summary": "z", "news_summary": "w"})
    assert "bear_view" in out
    assert "약세" in out["bear_view"]


def test_bear_handles_missing_summaries():
    node = create_bear_researcher(_FakeLLM("ok"))
    out = node({})
    assert isinstance(out["bear_view"], str)
