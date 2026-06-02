from langchain_core.messages import AIMessage
from tradingagents.schemas.research import InvestmentThesis, ResearchThesis
from tradingagents.agents.researchers.research_cluster import create_research_cluster


class _FakeBullBear:
    def __init__(self, content):
        self._c = content
    def invoke(self, prompt):
        return AIMessage(content=self._c)


class _FakeManager:
    """with_structured_output(InvestmentThesis) → .invoke → InvestmentThesis."""
    def __init__(self, thesis):
        self._t = thesis
    def with_structured_output(self, schema):
        return self
    def invoke(self, prompt):
        return self._t


def _state():
    return {"macro_summary": "m", "risk_summary": "r",
            "technical_summary": "t", "news_summary": "n"}


def test_cluster_synthesizes_research_thesis():
    thesis = InvestmentThesis(thesis_md="종합", conviction="high",
                              dominant_scenario="goldilocks",
                              key_risks=["인플레 재점화"])
    node = create_research_cluster(
        bull_llm=_FakeBullBear("강세"),
        bear_llm=_FakeBullBear("약세"),
        manager_llm=_FakeManager(thesis),
    )
    out = node(_state())
    rd = out["research_decision"]
    assert isinstance(rd, ResearchThesis)
    assert rd.conviction == "high"
    assert rd.dominant_scenario == "goldilocks"
    assert rd.bull_view == "강세"
    assert rd.bear_view == "약세"
    assert "research_debate_summary" in out


def test_cluster_manager_failure_falls_back():
    class _BadManager:
        def with_structured_output(self, schema):
            return self
        def invoke(self, prompt):
            raise RuntimeError("boom")
    node = create_research_cluster(
        bull_llm=_FakeBullBear("강세"), bear_llm=_FakeBullBear("약세"),
        manager_llm=_BadManager(),
    )
    out = node(_state())
    rd = out["research_decision"]
    assert rd.conviction == "medium"   # fallback neutral
