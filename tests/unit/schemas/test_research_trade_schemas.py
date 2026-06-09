import pytest
from tradingagents.schemas.research import InvestmentThesis, ResearchThesis
from tradingagents.schemas.portfolio import (
    OptimizationMethod, BucketAllocation, StockSelection,
)


def test_investment_thesis_defaults():
    t = InvestmentThesis(thesis_md="bull은 X, bear는 Y, 종합하면 Z")
    assert t.risk_tilt == "neutral"
    assert t.key_risks == []


def test_aum_weighted_enum():
    assert OptimizationMethod.AUM_WEIGHTED.value == "aum_weighted"


def test_bucket_allocation_and_stock_selection():
    ba = BucketAllocation(weights={"a1_cash": 0.3, "b1_kr_equity": 0.7})
    assert ba.weights["b1_kr_equity"] == 0.7
    ss = StockSelection(selections={"b1_kr_equity": ["A069500", "A102110"]})
    assert ss.selections["b1_kr_equity"] == ["A069500", "A102110"]
