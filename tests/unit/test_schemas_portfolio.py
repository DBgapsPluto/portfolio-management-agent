import pytest
from pydantic import ValidationError
from tradingagents.schemas.portfolio import (
    BucketTarget,
    CandidateSet,
    WeightVector,
    OptimizationMethod,
)

_8_BUCKET_WEIGHTS = {
    "kr_equity":             0.15,
    "global_equity":         0.20,
    "precious_metals":       0.08,
    "cyclical_commodity_fx": 0.14,
    "kr_bond":               0.15,
    "credit":                0.05,
    "global_duration":       0.13,
    "cash_mmf":              0.10,
}


def test_bucket_target_sums_to_one():
    bt = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="test")
    assert abs(bt.total - 1.0) < 1e-6


def test_bucket_rejects_non_unit_sum():
    bad = dict(_8_BUCKET_WEIGHTS)
    bad["kr_equity"] = 0.50  # sum != 1.0
    with pytest.raises(ValidationError):
        BucketTarget(weights=bad, rationale="bad")


def test_bucket_target_dict_access():
    bt = BucketTarget(weights=_8_BUCKET_WEIGHTS, rationale="test")
    assert bt["kr_equity"] == pytest.approx(0.15)
    assert bt.get("cash_mmf") == pytest.approx(0.10)
    assert set(bt.keys()) == set(_8_BUCKET_WEIGHTS.keys())
    assert sum(bt.values()) == pytest.approx(1.0)


def test_candidate_set_valid():
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A069500", "A005930"],
            "kr_bond": ["A411060"],
        },
        selection_criteria="Market cap > $500M, high liquidity",
        total_candidates=3,
    )
    assert len(cs.bucket_to_tickers["kr_equity"]) == 2
    assert cs.total_candidates == 3


def test_candidate_set_empty_raises():
    with pytest.raises(ValidationError):
        CandidateSet(
            bucket_to_tickers={},
            selection_criteria="test",
            total_candidates=0,
        )


def test_weight_vector_normalized():
    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A069500": 0.4, "A411060": 0.3, "A114260": 0.3},
        rationale="HRP based on 3y returns",
        expected_volatility=0.12,
        expected_sharpe=0.85,
    )
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6


def test_weight_vector_rejects_non_unit_sum():
    with pytest.raises(ValidationError):
        WeightVector(
            method=OptimizationMethod.MIN_VARIANCE,
            weights={"A069500": 0.5, "A411060": 0.3},
            rationale="sum < 1",
        )


def test_weight_vector_rejects_negative_weights():
    with pytest.raises(ValidationError):
        WeightVector(
            method=OptimizationMethod.RISK_PARITY,
            weights={"A069500": 1.2, "A411060": -0.2},
            rationale="negative weight",
        )


def test_weight_vector_empty_weights_raises():
    with pytest.raises(ValidationError):
        WeightVector(
            method=OptimizationMethod.BLACK_LITTERMAN,
            weights={},
            rationale="no weights",
        )


def test_optimization_method_enum():
    for method in OptimizationMethod:
        wv = WeightVector(
            method=method,
            weights={"A069500": 1.0},
            rationale="test",
        )
        assert wv.method == method
