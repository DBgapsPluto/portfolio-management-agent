import pytest
from tradingagents.schemas.research import InvestmentThesis, ResearchThesis
from tradingagents.schemas.portfolio import (
    OptimizationMethod, BucketAllocation, StockSelection,
)


def test_investment_thesis_defaults():
    t = InvestmentThesis(thesis_md="bull은 X, bear는 Y, 종합하면 Z")
    assert t.conviction == "medium"
    assert t.dominant_scenario == "neutral"
    assert t.key_risks == []


def test_research_thesis_compat_fields():
    t = ResearchThesis(conviction="high", dominant_scenario="goldilocks",
                       thesis_md="t", bull_view="b", bear_view="r")
    assert getattr(t, "dominant_scenario") == "goldilocks"
    assert getattr(t, "conviction") == "high"
    assert getattr(t, "factor_scores", None) is None


def test_aum_weighted_enum():
    assert OptimizationMethod.AUM_WEIGHTED.value == "aum_weighted"


def test_bucket_allocation_and_stock_selection():
    ba = BucketAllocation(weights={"a1_cash": 0.3, "b1_kr_equity": 0.7})
    assert ba.weights["b1_kr_equity"] == 0.7
    ss = StockSelection(selections={"b1_kr_equity": ["A069500", "A102110"]})
    assert ss.selections["b1_kr_equity"] == ["A069500", "A102110"]
