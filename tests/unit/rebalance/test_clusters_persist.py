from tradingagents.agents.managers.portfolio_manager import _build_full_trace_portfolio
from tradingagents.schemas.portfolio import WeightVector, OptimizationMethod


def test_clusters_persisted():
    state = {
        "as_of_date": "2026-06-07", "capital_krw": 1_000_000_000,
        "weight_vector": WeightVector(method=OptimizationMethod.AUM_WEIGHTED,
                                      weights={"A069500": 1.0}, rationale="t"),
        "correlation_clusters": [{"members": ["A069500", "A229200"], "avg_corr": 0.8}],
    }
    out = _build_full_trace_portfolio(state)
    assert out["correlation_clusters"] == [
        {"members": ["A069500", "A229200"], "avg_corr": 0.8}]


def test_clusters_default_empty():
    state = {
        "as_of_date": "2026-06-07", "capital_krw": 1_000_000_000,
        "weight_vector": WeightVector(method=OptimizationMethod.AUM_WEIGHTED,
                                      weights={"A069500": 1.0}, rationale="t"),
    }
    out = _build_full_trace_portfolio(state)
    assert out["correlation_clusters"] == []
