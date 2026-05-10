"""Tests for PortfolioAllocator (D4 + D12 + D13)."""
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator, _hrp_per_bucket, _build_sector_mapper_and_bounds,
)
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod,
)
from tradingagents.skills.portfolio.method_picker import MethodChoice


def _bucket_target() -> BucketTarget:
    return BucketTarget(
        kr_equity=0.20, global_equity=0.30, fx_commodity=0.10,
        bond=0.30, cash_mmf=0.10,
        rationale="test",
    )


def _candidates() -> CandidateSet:
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A069500"],
            "global_equity": ["A360750"],
            "fx_commodity": ["A411060"],
            "bond": ["A114260"],
            "cash_mmf": ["A459580"],
        },
        selection_criteria="test",
        total_candidates=5,
    )


def test_hrp_per_bucket_single_asset_per_bucket():
    """When each bucket has 1 ticker, HRP allocation = 100% within bucket × bucket weight."""
    rng = np.random.default_rng(42)
    n = 252
    returns = pd.DataFrame({
        "A069500": rng.normal(0.001, 0.01, n),
        "A360750": rng.normal(0.001, 0.01, n),
        "A411060": rng.normal(0.001, 0.01, n),
        "A114260": rng.normal(0.0005, 0.005, n),
        "A459580": rng.normal(0.0001, 0.001, n),
    })
    wv = _hrp_per_bucket(returns, _candidates(), _bucket_target())
    # Each ticker gets its bucket target weight (since 1 ticker per bucket)
    assert wv.weights["A069500"] == pytest.approx(0.20, abs=0.01)
    assert wv.weights["A360750"] == pytest.approx(0.20, abs=0.01)  # capped from 0.30 to 0.20
    # Verify cap respected
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())


def test_hrp_per_bucket_iterative_redistribution():
    """REGRESSION (D12): iterative water-filling converges when single-pass fails.

    Bucket=0.80, 4 candidates with HRP weights (0.6, 0.2, 0.1, 0.1):
    scaled = (0.48, 0.16, 0.08, 0.08), sum 0.80
    Single-pass: cap → (0.20, 0.16, 0.08, 0.08) sum 0.52, residual 0.28 redistributed
                 → (0.20, 0.20, 0.173, 0.173) sum 0.747 (WRONG — bucket target 0.80 missed)
    Iterative: keeps redistributing until convergence.
    """
    # Simulate: single bucket with 4 tickers, target 0.80
    candidates = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A1", "A2", "A3", "A4"],
            "global_equity": [], "fx_commodity": [], "bond": [], "cash_mmf": [],
        },
        selection_criteria="test", total_candidates=4,
    )
    target = BucketTarget(
        kr_equity=0.80, global_equity=0.0, fx_commodity=0.0,
        bond=0.20, cash_mmf=0.0,
        rationale="extreme test",
    )
    # We need a 5th asset for bond=0.20 to be filled, otherwise total < 1.0
    # Add a bond asset:
    candidates.bucket_to_tickers["bond"] = ["B1"]
    candidates = candidates.model_copy(update={"total_candidates": 5})

    rng = np.random.default_rng(0)
    n = 200
    # Assets in kr_equity highly correlated (HRP gives uneven weights)
    factor = rng.normal(0, 1, n)
    returns = pd.DataFrame({
        "A1": factor * 1.0 + rng.normal(0, 0.01, n),
        "A2": factor * 0.5 + rng.normal(0, 0.05, n),
        "A3": factor * 0.3 + rng.normal(0, 0.08, n),
        "A4": factor * 0.2 + rng.normal(0, 0.1, n),
        "B1": rng.normal(0, 0.005, n),
    })
    wv = _hrp_per_bucket(returns, candidates, target)

    # All weights ≤ 0.20 cap
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
    # Bucket sum approximately reaches target (within iterative tolerance)
    kr_sum = sum(wv.weights[t] for t in ["A1", "A2", "A3", "A4"] if t in wv.weights)
    assert kr_sum >= 0.79, f"kr_equity bucket sum {kr_sum} < 0.79"


def test_sector_mapper_strict_then_relaxed():
    candidates = _candidates()
    target = _bucket_target()
    # Strict
    _, lower, upper = _build_sector_mapper_and_bounds(candidates, target, attempts=0)
    assert lower["kr_equity"] == upper["kr_equity"] == 0.20
    # Relaxed
    _, lower, upper = _build_sector_mapper_and_bounds(candidates, target, attempts=1)
    assert lower["kr_equity"] == 0.15  # 0.20 - 0.05
    assert upper["kr_equity"] == 0.25  # 0.20 + 0.05
