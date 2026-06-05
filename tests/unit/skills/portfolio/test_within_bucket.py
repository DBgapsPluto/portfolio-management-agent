import pytest
from tradingagents.skills.portfolio.within_bucket import (
    aggregate_weights_to_buckets, aum_weighted_allocation,
    drop_negligible_holdings, InfeasibleBucket, SINGLE_CAP,
)


def test_aggregate_weights_to_buckets_sums_by_bucket():
    selections = {"b1_kr_equity": ["A", "B"], "b8_cyclical_commodity": ["C"]}
    out = aggregate_weights_to_buckets({"A": 0.3, "B": 0.2, "C": 0.5}, selections)
    assert out["b1_kr_equity"] == pytest.approx(0.5)
    assert out["b8_cyclical_commodity"] == pytest.approx(0.5)


def test_aggregate_weights_to_buckets_excludes_cutoff_holdings():
    """컷오프로 weights 에서 빠진 종목의 bucket 은 realized 집계에서 자동 제외 —
    bucket_target/philosophy 가 실현 비중을 정확히 반영하는 핵심."""
    selections = {"b1_kr_equity": ["A", "B"], "b9_risk_credit": ["C"]}
    out = aggregate_weights_to_buckets({"A": 0.6, "B": 0.4}, selections)  # C 컷오프됨
    assert "b9_risk_credit" not in out
    assert out["b1_kr_equity"] == pytest.approx(1.0)


def test_drop_negligible_removes_residual_keeps_diversifiers():
    """실행상 무의미한 잔여(0.5%)는 제거하되, 분산 목적 소액(3.5%)은 보존."""
    w = {f"big{i}": 0.16 for i in range(6)}      # 6×16% = 96%
    w["residual"] = 0.005                          # 0.5% — 실행상 잔여
    w["div"] = 0.035                               # 3.5% — 분산 포지션
    out = drop_negligible_holdings(w, floor=0.01)
    assert "residual" not in out                   # 잔여 제거
    assert "div" in out                            # 분산은 보존 (비율 컷오프 아님)
    assert sum(out.values()) == pytest.approx(1.0)


def test_drop_negligible_redistributes_proportionally():
    """제거 후 남은 비중은 비례 재분배 (상대 순서 보존)."""
    w = {"a": 0.50, "b": 0.30, "c": 0.195, "residual": 0.005}
    out = drop_negligible_holdings(w, floor=0.01)
    assert out["a"] > out["b"] > out["c"]
    assert sum(out.values()) == pytest.approx(1.0)


def test_drop_negligible_respects_single_cap_after_redistribute():
    """비례 재분배가 큰 포지션을 20% 위로 밀면 cap 재적용."""
    w = {"big": 0.40, "b": 0.15, "c": 0.15, "d": 0.15, "e": 0.145, "residual": 0.005}
    out = drop_negligible_holdings(w, floor=0.01)
    assert all(v <= SINGLE_CAP + 1e-9 for v in out.values())
    assert sum(out.values()) == pytest.approx(1.0)


def test_drop_negligible_noop_when_too_few_holdings():
    """제거 후 5종목 미만이면(20% cap 하 합=1 불가) 원본 유지."""
    w = {"a": 0.50, "b": 0.49, "residual": 0.01}
    out = drop_negligible_holdings(w, floor=0.02)
    assert out == w


def test_drop_negligible_floor_zero_is_noop():
    w = {"a": 0.5, "b": 0.5}
    assert drop_negligible_holdings(w, floor=0.0) == w


def test_single_stock_takes_full_bucket_weight():
    out = aum_weighted_allocation(
        {"b1_kr_equity": 0.10}, {"b1_kr_equity": ["A1"]}, {"A1": 1000.0},
    )
    assert out["A1"] == pytest.approx(0.10)


def test_aum_proportional_split():
    # AUM ratio 3:2 — neither stock exceeds SINGLE_CAP (0.18 and 0.12 < 0.20)
    out = aum_weighted_allocation(
        {"b1_kr_equity": 0.30},
        {"b1_kr_equity": ["A1", "A2"]},
        {"A1": 150.0, "A2": 100.0},
    )
    assert out["A1"] == pytest.approx(0.30 * 0.60)
    assert out["A2"] == pytest.approx(0.30 * 0.40)


def test_cap_water_filling_redistributes_excess():
    out = aum_weighted_allocation(
        {"b1_kr_equity": 0.30},
        {"b1_kr_equity": ["A1", "A2"]},
        {"A1": 900.0, "A2": 100.0},
    )
    assert out["A1"] == pytest.approx(SINGLE_CAP)
    assert out["A2"] == pytest.approx(0.10)
    assert sum(out.values()) == pytest.approx(0.30)


def test_multi_bucket_sums_to_one():
    out = aum_weighted_allocation(
        {"a1_cash": 0.40, "b1_kr_equity": 0.60},
        {"a1_cash": ["C1", "C2"], "b1_kr_equity": ["E1", "E2", "E3"]},
        {"C1": 1.0, "C2": 1.0, "E1": 1.0, "E2": 1.0, "E3": 1.0},
    )
    assert sum(out.values()) == pytest.approx(1.0)


def test_zero_weight_bucket_skipped():
    # a1_cash weight=0 is skipped; b1_kr_equity weight=0.20 (≤ SINGLE_CAP) gets full alloc
    out = aum_weighted_allocation(
        {"a1_cash": 0.0, "b1_kr_equity": 0.20},
        {"a1_cash": ["C1"], "b1_kr_equity": ["E1"]},
        {"C1": 1.0, "E1": 1.0},
    )
    assert "C1" not in out
    assert out["E1"] == pytest.approx(0.20)


def test_multi_round_water_filling():
    # weight 0.70 over 4 stocks; AUM skewed so capping happens over 2 rounds:
    # round1 caps A1, round2 caps A2, residual splits equally to A3/A4.
    out = aum_weighted_allocation(
        {"b1_kr_equity": 0.70},
        {"b1_kr_equity": ["A1", "A2", "A3", "A4"]},
        {"A1": 10000.0, "A2": 1000.0, "A3": 50.0, "A4": 50.0},
    )
    assert out["A1"] == pytest.approx(SINGLE_CAP)
    assert out["A2"] == pytest.approx(SINGLE_CAP)
    assert all(w <= SINGLE_CAP + 1e-9 for w in out.values())
    assert out["A3"] == pytest.approx(out["A4"])          # equal AUM → equal residual
    assert sum(out.values()) == pytest.approx(0.70)


def test_zero_aum_falls_back_to_equal_split():
    out = aum_weighted_allocation(
        {"b1_kr_equity": 0.30},
        {"b1_kr_equity": ["A1", "A2"]},
        {},   # no AUM info → equal split
    )
    assert out["A1"] == pytest.approx(0.15)
    assert out["A2"] == pytest.approx(0.15)


def test_infeasible_when_too_few_stocks_for_weight():
    with pytest.raises(InfeasibleBucket):
        aum_weighted_allocation(
            {"b1_kr_equity": 0.50},
            {"b1_kr_equity": ["A1", "A2"]},
            {"A1": 1.0, "A2": 1.0},
        )


def test_infeasible_when_bucket_has_no_stocks():
    with pytest.raises(InfeasibleBucket):
        aum_weighted_allocation(
            {"b1_kr_equity": 0.10}, {"b1_kr_equity": []}, {},
        )
