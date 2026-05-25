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
from tradingagents.skills.research.factor_to_bucket import BUCKETS, FACTORS


def test_equal_weight_sums_to_one_per_bucket() -> None:
    """1/N: 각 bucket = 0.2, sum=1.0."""
    w = equal_weight()
    assert set(w.keys()) == set(BUCKETS)
    for b in BUCKETS:
        assert w[b] == pytest.approx(0.2)
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


def test_hand_coded_beta_pr2a_pre_45_entries() -> None:
    """45 entries (9 factors × 5 buckets)."""
    assert len(HAND_CODED_BETA_PR2A_PRE) == 45
    for f in FACTORS:
        for b in BUCKETS:
            assert (f, b) in HAND_CODED_BETA_PR2A_PRE


def test_hand_coded_beta_pr2a_pre_row_sums_zero() -> None:
    """Hand-coded prior 의 row sum = 0 invariant (pre-PR2a 설계)."""
    for f in FACTORS:
        row_sum = sum(
            HAND_CODED_BETA_PR2A_PRE.get((f, b), 0.0) for b in BUCKETS
        )
        assert abs(row_sum) < 1e-6, f"{f}: row sum {row_sum}"
