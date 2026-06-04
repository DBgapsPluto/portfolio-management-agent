import pytest
from tradingagents.skills.portfolio.within_bucket import (
    aum_weighted_allocation, InfeasibleBucket, SINGLE_CAP,
)


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
