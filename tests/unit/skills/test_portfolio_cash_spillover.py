"""cash_spillover unit tests — conviction + redistribution invariants."""
import logging

import numpy as np
import pandas as pd
import pytest

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.cash_spillover import (
    CASH_CAP_FOR_SPILLOVER_TARGET,
    SPILLOVER_THRESHOLD_BY_BUCKET,
    SPILLOVER_THRESHOLD_DEFAULT,
    ConvictionResult,
    adjust_bucket_targets,
    compute_bucket_conviction,
)


def _make_returns(tickers: list[str], n_days: int = 252, vol: float = 0.02, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = rng.normal(0.0, vol, size=(n_days, len(tickers)))
    return pd.DataFrame(data, columns=tickers)


def test_conviction_full_strength():
    """mean_alpha = threshold AND ENB = √N → conviction = 1.0, spillover_ratio = 0."""
    tickers = ["A000001", "A000002", "A000003", "A000004"]
    returns = _make_returns(tickers, seed=1)
    # alpha 평균이 SPILLOVER_THRESHOLD_DEFAULT 와 동일하게 설계
    alpha_scores = {t: SPILLOVER_THRESHOLD_DEFAULT for t in tickers}
    result = compute_bucket_conviction("kr_equity", tickers, alpha_scores, returns)
    assert result.bucket == "kr_equity"
    assert result.n_chosen == 4
    assert result.mean_alpha == pytest.approx(SPILLOVER_THRESHOLD_DEFAULT, abs=1e-9)
    assert result.threshold == SPILLOVER_THRESHOLD_DEFAULT
    # ENB 가 √N 에 가까우면 conviction ≈ 1
    assert result.conviction >= 0.9
    assert result.spillover_ratio == pytest.approx(0.0, abs=0.1)


def test_conviction_zero_alpha():
    """mean_alpha = 0 → conviction = 0, spillover_ratio = 1.0."""
    tickers = ["A000001", "A000002"]
    returns = _make_returns(tickers, seed=2)
    alpha_scores = {t: 0.0 for t in tickers}
    result = compute_bucket_conviction("kr_equity", tickers, alpha_scores, returns)
    assert result.bucket == "kr_equity"
    assert result.n_chosen == 2
    assert result.mean_alpha == pytest.approx(0.0, abs=1e-9)
    assert result.threshold == SPILLOVER_THRESHOLD_DEFAULT
    assert result.conviction == pytest.approx(0.0, abs=1e-9)
    assert result.spillover_ratio == pytest.approx(1.0, abs=1e-9)


def test_conviction_empty_chosen():
    """chosen = [] → conviction 0, spillover 1.0, ENB 0."""
    returns = _make_returns(["A000001"], seed=3)
    result = compute_bucket_conviction("fx_commodity", [], {}, returns)
    assert result.n_chosen == 0
    assert result.mean_alpha == 0.0
    assert result.enb == 0.0
    assert result.conviction == 0.0
    assert result.spillover_ratio == 1.0


def test_conviction_fx_commodity_uses_specific_threshold():
    """fx_commodity 는 threshold 0.15 사용."""
    tickers = ["A411060", "A261220"]
    returns = _make_returns(tickers, seed=4)
    alpha_scores = {t: 0.1 for t in tickers}
    result = compute_bucket_conviction("fx_commodity", tickers, alpha_scores, returns)
    assert result.threshold == SPILLOVER_THRESHOLD_BY_BUCKET["fx_commodity"]
    assert result.threshold == 0.15


def test_conviction_single_chosen():
    """N=1 → ENB = 1. 공식 (mean_alpha/threshold) × (1/1) = mean_alpha/threshold."""
    tickers = ["A411060"]
    returns = _make_returns(tickers, seed=5)
    alpha_scores = {"A411060": 0.075}  # threshold/2
    result = compute_bucket_conviction("fx_commodity", tickers, alpha_scores, returns)
    assert result.n_chosen == 1
    assert result.enb == pytest.approx(1.0, abs=1e-9)
    expected_conviction = 0.075 / 0.15 * 1.0 / 1.0  # = 0.5
    assert result.conviction == pytest.approx(expected_conviction, abs=1e-9)
    assert result.spillover_ratio == pytest.approx(0.5, abs=1e-9)
