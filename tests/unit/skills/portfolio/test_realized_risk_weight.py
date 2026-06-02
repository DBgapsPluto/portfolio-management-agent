import pytest
from tradingagents.skills.portfolio.within_bucket import realized_risk_weight


def test_sums_only_위험_flagged():
    weights = {"A1": 0.5, "A2": 0.3, "A3": 0.2}
    risk_flag = {"A1": "위험", "A2": "안전", "A3": "위험"}
    assert realized_risk_weight(weights, risk_flag) == pytest.approx(0.7)


def test_missing_flag_treated_as_안전():
    weights = {"A1": 0.6, "A2": 0.4}
    assert realized_risk_weight(weights, {"A1": "위험"}) == pytest.approx(0.6)
