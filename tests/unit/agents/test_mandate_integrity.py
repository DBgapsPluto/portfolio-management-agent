"""Stage 5 Commit A ③ — Weight integrity NaN/Inf 사전 검증."""
import math

import pytest

from tradingagents.agents.validator.mandate_validator import (
    FLOOR_BY_MODE, _check_weight_integrity, _resolve_rebalance_mode,
)
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector


def _wv(weights):
    """WeightVector 우회 — Pydantic 검증을 통과한 객체에 직접 mutate."""
    base = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A001": 0.5, "A002": 0.5},
        rationale="t",
    )
    object.__setattr__(base, "weights", weights)
    return base


def test_valid_weights_pass():
    wv = _wv({"A001": 0.5, "A002": 0.5})
    assert _check_weight_integrity(wv) == []


def test_nan_weight_detected():
    wv = _wv({"A001": float("nan"), "A002": 1.0})
    issues = _check_weight_integrity(wv)
    assert any(v.rule == "weight_validity" for v in issues)
    assert all(v.severity == "hard" for v in issues)


def test_inf_weight_detected():
    wv = _wv({"A001": float("inf"), "A002": 0.5})
    issues = _check_weight_integrity(wv)
    assert any(v.rule == "weight_validity" for v in issues)


def test_negative_weight_detected():
    wv = _wv({"A001": -0.1, "A002": 1.1})
    issues = _check_weight_integrity(wv)
    assert any(v.rule == "weight_validity" for v in issues)


def test_sum_not_one_detected():
    wv = _wv({"A001": 0.3, "A002": 0.3})  # sum=0.6
    issues = _check_weight_integrity(wv)
    assert any(v.rule == "weight_sum" for v in issues)


def test_empty_weights_detected():
    wv = _wv({})
    issues = _check_weight_integrity(wv)
    assert any(v.rule == "weight_validity" for v in issues)


def test_floor_by_mode_definition():
    assert FLOOR_BY_MODE["initial"] == (0.80, 5)
    assert FLOOR_BY_MODE["monthly"] == (0.10, 20)


def test_resolve_mode_explicit():
    assert _resolve_rebalance_mode({"rebalance_mode": "monthly"}) == "monthly"
    assert _resolve_rebalance_mode({"rebalance_mode": "initial"}) == "initial"


def test_resolve_mode_backward_compat():
    # explicit 없으면 previous_portfolio 유무로 분기
    assert _resolve_rebalance_mode({}) == "initial"
    assert _resolve_rebalance_mode(
        {"previous_portfolio": {"weights": {"A001": 1.0}}}
    ) == "monthly"


def test_resolve_mode_unknown_explicit_falls_back():
    # explicit 값이 FLOOR_BY_MODE에 없으면 backward-compat
    assert _resolve_rebalance_mode(
        {"rebalance_mode": "daily"}
    ) == "initial"
    assert _resolve_rebalance_mode(
        {"rebalance_mode": "weekly",
         "previous_portfolio": {"weights": {"A001": 1.0}}}
    ) == "monthly"
