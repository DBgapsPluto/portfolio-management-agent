"""Unit tests for benchmarks.py — 5 bucket weight functions."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.benchmarks import (
    HAND_CODED_BETA_PR2A_PRE,
    equal_weight,
    kr_tilted_60_40,
    risk_parity,
)
from tradingagents.skills.research.factor_to_bucket import BUCKETS

# HAND_CODED_BETA_PR2A_PRE 는 PR2b 벤치마크용으로 동결된 pre-PR2a 역사적
# 스냅샷(git 3572d03)이다. live INITIAL_BETA 가 아니므로 현재의 12-factor/
# 8-bucket 스키마로 확장하면 안 된다. 아래 OLD_* 는 스냅샷 자체 키에서
# 직접 도출한 OLD 스키마(10 factor × 5 bucket)다.
OLD_FACTORS: tuple[str, ...] = tuple(
    sorted({f for (f, _b) in HAND_CODED_BETA_PR2A_PRE}),
)
OLD_BUCKETS: tuple[str, ...] = tuple(
    sorted({b for (_f, b) in HAND_CODED_BETA_PR2A_PRE}),
)


def test_equal_weight_sums_to_one_per_bucket() -> None:
    """1/N: 각 bucket = 1/len(BUCKETS), sum=1.0 (live 8-bucket 스키마 추종)."""
    w = equal_weight()
    assert set(w.keys()) == set(BUCKETS)
    for b in BUCKETS:
        assert w[b] == pytest.approx(1.0 / len(BUCKETS))
    assert sum(w.values()) == pytest.approx(1.0)


def test_kr_tilted_60_40_specific_weights() -> None:
    """60-40 KR-tilted: kr_eq 0.20 + gl_eq 0.40 + bond 0.40."""
    w = kr_tilted_60_40()
    assert w["kr_equity"] == pytest.approx(0.20)
    assert w["global_equity"] == pytest.approx(0.40)
    assert w["bond"] == pytest.approx(0.40)
    assert w["fx_commodity"] == pytest.approx(0.0)
    assert w["cash_mmf"] == pytest.approx(0.0)
    assert sum(w.values()) == pytest.approx(1.0)


def test_risk_parity_weights_sum_to_one_and_inverse_to_vol() -> None:
    """Risk parity: σ-inverse weighted."""
    rng = np.random.default_rng(42)
    n = 100
    returns = pd.DataFrame(
        {b: rng.normal(0, 0.01 * (i + 1), n) for i, b in enumerate(BUCKETS)},
    )
    w = risk_parity(returns, window=60)
    assert set(w.keys()) == set(BUCKETS)
    assert sum(w.values()) == pytest.approx(1.0, rel=1e-6)
    # Lower-vol bucket (first) should have higher weight than highest-vol bucket (last).
    assert w[BUCKETS[0]] > w[BUCKETS[-1]]


def test_hand_coded_beta_pr2a_pre_50_entries() -> None:
    """50 entries (10 OLD factors × 5 OLD buckets) — 동결 스냅샷이라 OLD 스키마로 검증."""
    assert len(HAND_CODED_BETA_PR2A_PRE) == 50
    assert len(OLD_FACTORS) == 10
    assert len(OLD_BUCKETS) == 5
    for f in OLD_FACTORS:
        for b in OLD_BUCKETS:
            assert (f, b) in HAND_CODED_BETA_PR2A_PRE


def test_hand_coded_beta_pr2a_pre_row_sums_zero() -> None:
    """Hand-coded prior 의 row sum = 0 invariant (pre-PR2a 설계, OLD 스키마)."""
    for f in OLD_FACTORS:
        row_sum = sum(
            HAND_CODED_BETA_PR2A_PRE.get((f, b), 0.0) for b in OLD_BUCKETS
        )
        assert abs(row_sum) < 1e-6, f"{f}: row sum {row_sum}"
