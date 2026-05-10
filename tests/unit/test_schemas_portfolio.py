import pytest
from pydantic import ValidationError
from tradingagents.schemas.portfolio import (
    BucketTarget,
    CandidateSet,
    WeightVector,
    OptimizationMethod,
)


def test_bucket_target_sums_to_one():
    bt = BucketTarget(
        kr_equity=0.15,
        global_equity=0.30,
        fx_commodity=0.10,
        bond=0.35,
        cash_mmf=0.10,
        rationale="Recession-disinflation regime, defensive tilt",
    )
    assert abs(bt.total - 1.0) < 1e-6


def test_bucket_rejects_non_unit_sum():
    with pytest.raises(ValidationError):
        BucketTarget(
            kr_equity=0.5,
            global_equity=0.5,
            fx_commodity=0.5,
            bond=0.0,
            cash_mmf=0.0,
            rationale="bad",
        )


def test_bucket_target_risk_asset_weight():
    bt = BucketTarget(
        kr_equity=0.20,
        global_equity=0.25,
        fx_commodity=0.05,
        bond=0.35,
        cash_mmf=0.15,
        rationale="test",
    )
    expected_risk = 0.20 + 0.25 + 0.05
    assert abs(bt.risk_asset_weight - expected_risk) < 1e-6


def test_candidate_set_valid():
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A069500", "A005930"],
            "bond": ["A411060"],
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
