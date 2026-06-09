from tradingagents.agents.researchers.research_cluster import create_research_cluster
from tradingagents.schemas.research import InvestmentThesis


def test_research_cluster_outputs_risk_tilt(monkeypatch):
    import tradingagents.agents.researchers.research_cluster as rc
    monkeypatch.setattr(rc, "invoke_structured_obj",
                        lambda *a, **k: InvestmentThesis(thesis_md="t", risk_tilt="defensive", key_risks=["r"]))
    monkeypatch.setattr(rc, "create_bull_researcher", lambda llm: (lambda s: {"bull_view": "B"}))
    monkeypatch.setattr(rc, "create_bear_researcher", lambda llm: (lambda s: {"bear_view": "R"}))
    node = create_research_cluster(object(), object(), object())
    out = node({})
    assert out["research_decision"].risk_tilt == "defensive"
    assert "risk_tilt: defensive" in out["research_debate_summary"]


def test_research_cluster_fallback_neutral(monkeypatch):
    # manager LLM 실패 시 invoke_structured_obj 가 fallback 을 반환 → risk_tilt=neutral
    import tradingagents.agents.researchers.research_cluster as rc
    monkeypatch.setattr(rc, "invoke_structured_obj",
                        lambda structured, prompt, fallback, name: fallback)
    monkeypatch.setattr(rc, "create_bull_researcher", lambda llm: (lambda s: {"bull_view": "B"}))
    monkeypatch.setattr(rc, "create_bear_researcher", lambda llm: (lambda s: {"bear_view": "R"}))
    node = create_research_cluster(object(), object(), object())
    out = node({})
    assert out["research_decision"].risk_tilt == "neutral"
