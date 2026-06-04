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
    t = ResearchThesis(conviction="high", dominant_scenario="kr_stress",
                       thesis_md="t", bull_view="b", bear_view="r")
    assert getattr(t, "dominant_scenario") == "kr_stress"
    assert getattr(t, "conviction") == "high"
    assert getattr(t, "factor_scores", None) is None


def test_dominant_scenario_coerces_unknown_to_neutral():
    # 구 라벨 / free text (enum 밖) → neutral (replay·구 archive 호환)
    assert ResearchThesis(dominant_scenario="growth_inflation").dominant_scenario == "neutral"
    assert InvestmentThesis(thesis_md="x", dominant_scenario="goldilocks").dominant_scenario == "neutral"
    # 유효 직교 라벨은 보존
    assert ResearchThesis(dominant_scenario="kr_boom").dominant_scenario == "kr_boom"
    assert InvestmentThesis(thesis_md="x", dominant_scenario="ai_concentration").dominant_scenario == "ai_concentration"


def test_aum_weighted_enum():
    assert OptimizationMethod.AUM_WEIGHTED.value == "aum_weighted"


def test_bucket_allocation_and_stock_selection():
    ba = BucketAllocation(weights={"a1_cash": 0.3, "b1_kr_equity": 0.7})
    assert ba.weights["b1_kr_equity"] == 0.7
    ss = StockSelection(selections={"b1_kr_equity": ["A069500", "A102110"]})
    assert ss.selections["b1_kr_equity"] == ["A069500", "A102110"]
