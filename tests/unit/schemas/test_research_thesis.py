from tradingagents.schemas.research import ResearchThesis, InvestmentThesis

def test_research_thesis_defaults_neutral():
    rt = ResearchThesis()
    assert rt.risk_tilt == "neutral"

def test_research_thesis_accepts_risk_tilt():
    rt = ResearchThesis(risk_tilt="defensive", thesis_md="x", key_risks=["a"])
    assert rt.risk_tilt == "defensive"

def test_investment_thesis_risk_tilt():
    it = InvestmentThesis(thesis_md="x", risk_tilt="offensive")
    assert it.risk_tilt == "offensive"
