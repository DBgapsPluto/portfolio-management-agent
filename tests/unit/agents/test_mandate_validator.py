from pathlib import Path

import pytest

from tradingagents.agents.validator.mandate_validator import create_mandate_validator
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector


def test_mandate_validator_pass(tmp_path):
    """Test: validator passes on compliant weights."""
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={
            "A069500": 0.20, "A360750": 0.20, "A411060": 0.20,
            "A114260": 0.20, "A459580": 0.20,
        },
        rationale="balanced",
    )
    state = {
        "weight_vector": wv,
        "universe_path": str(universe_json),
        "capital_krw": 1_000_000_000,
        "correlation_clusters": [],
        "previous_portfolio": None,
    }
    node = create_mandate_validator()
    result = node(state)
    # Should pass: all single weights = 0.20, risk asset = 0.60, turnover 100% (initial)
    assert result["validation_passed"] is True
    assert result["allocation_feedback"] == []


def test_mandate_validator_fail_single_cap(tmp_path):
    """Test: validator fails when single ETF exceeds 20% cap."""
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={
            "A069500": 0.25,  # > 20%
            "A360750": 0.15, "A411060": 0.10,
            "A114260": 0.30, "A459580": 0.20,
        },
        rationale="bad",
    )
    state = {
        "weight_vector": wv,
        "universe_path": str(universe_json),
        "capital_krw": 1_000_000_000,
        "correlation_clusters": [],
        "previous_portfolio": None,
    }
    node = create_mandate_validator()
    result = node(state)
    assert result["validation_passed"] is False
    assert len(result["allocation_feedback"]) >= 1
    assert any(v.rule == "single_etf_cap" for v in result["allocation_feedback"])


# ---------- Stage 5 audit (2026-05-26) tests ----------


def test_mandate_validator_attribution_records_check_counts():
    """Stage 5 audit Task 0: mandate_validator_attribution 가 check_counts 와
    hard_violations 를 모두 채움 (validation_passed=True 정상 path).
    """
    import math
    from pathlib import Path
    from tradingagents.agents.validator.mandate_validator import create_mandate_validator
    from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector

    universe_path = Path("data/universe.json")
    if not universe_path.exists():
        pytest.skip("universe.json not present in test env")

    # passing portfolio — 2 ETF, 단일 cap/risk cap 안 넘김
    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={"A114260": 0.6, "A459580": 0.4},  # bond + cash
        rationale="test passing",
    )
    state = {
        "weight_vector": wv,
        "universe_path": str(universe_path),
        "capital_krw": 10_000_000_000,
        "correlation_clusters": [],
        "previous_portfolio": None,
    }
    node = create_mandate_validator()
    out = node(state)

    mv_attr = out.get("mandate_validator_attribution", {})
    assert "check_counts" in mv_attr
    # 4 check + integrity
    for name in ("integrity", "universe", "concentration", "correlation", "turnover"):
        assert name in mv_attr["check_counts"]
        assert "hard" in mv_attr["check_counts"][name]
        assert "soft" in mv_attr["check_counts"][name]
    assert "rebalance_mode" in mv_attr
    assert mv_attr["rebalance_mode"] == "initial"  # previous_portfolio None → initial
    assert mv_attr["turnover_floor"] == 0.80   # TURNOVER_FLOOR_INITIAL
    assert "hard_violations" in mv_attr
    assert "input_present" in mv_attr


def test_mandate_validator_attribution_records_hard_violations():
    """Stage 5 audit Task 0: hard violation 시 hard_violations list 채움 (top-5)."""
    import pytest as _pt
    from pathlib import Path
    from tradingagents.agents.validator.mandate_validator import create_mandate_validator
    from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector

    universe_path = Path("data/universe.json")
    if not universe_path.exists():
        _pt.skip("universe.json not present")

    # single asset cap 위반 — A114260 30% > 20%
    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={"A114260": 0.3, "A459580": 0.7},
        rationale="test violation",
    )
    state = {
        "weight_vector": wv,
        "universe_path": str(universe_path),
        "capital_krw": 10_000_000_000,
        "correlation_clusters": [],
        "previous_portfolio": None,
    }
    node = create_mandate_validator()
    out = node(state)

    mv_attr = out["mandate_validator_attribution"]
    assert mv_attr["validation_passed"] is False
    assert mv_attr["check_counts"]["concentration"]["hard"] >= 1
    assert len(mv_attr["hard_violations"]) >= 1
    rules = {v["rule"] for v in mv_attr["hard_violations"]}
    assert "single_etf_cap" in rules


def test_mandate_named_const_present():
    """Stage 5 audit Task 1: 4 check + validator 의 named const 존재 검증."""
    from tradingagents.skills.mandate import (
        concentration_check as cc,
        correlation_check as corc,
        turnover_check as tc,
    )
    from tradingagents.agents.validator import mandate_validator as mv

    assert cc.HARD_SINGLE_CAP == 0.20
    assert cc.HARD_RISK_ASSET_CAP == 0.70
    assert cc.FLOAT_TOLERANCE == 1e-6

    assert corc.DEFAULT_CLUSTER_CAP == 0.25
    assert corc.FLOAT_TOLERANCE == 1e-6

    assert tc.TURNOVER_TOLERANCE == 1e-9

    assert mv.TURNOVER_FLOOR_INITIAL == 0.80
    assert mv.TURNOVER_FLOOR_MONTHLY == 0.10
    assert mv.WEIGHT_SUM_TOLERANCE == 1e-3
