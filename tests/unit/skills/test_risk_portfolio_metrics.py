"""Stage 3.5 portfolio_metrics — HHI/cluster/CVaR 등."""
import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.schemas.technical import Cluster
from tradingagents.skills.risk.portfolio_metrics import compute_portfolio_numerics


def _returns(tickers, n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {t: rng.normal(0.0005, 0.012, n) for t in tickers}, index=idx,
    )


def _wv(weights):
    return WeightVector(
        method=OptimizationMethod.HRP, weights=weights,
        rationale="t",
    )


def test_hhi_for_uniform_weights():
    """5 ticker × 0.20 → HHI = 5 × 0.04 = 0.20."""
    wv = _wv({f"A{i:03d}": 0.20 for i in range(1, 6)})
    returns = _returns(list(wv.weights.keys()))
    n = compute_portfolio_numerics(wv, returns)
    assert n.hhi == pytest.approx(0.20, abs=0.001)


def test_hhi_for_concentrated_weights():
    """1 ticker 0.5, 5 ticker 0.10 → HHI = 0.25 + 5 × 0.01 = 0.30."""
    wv = _wv({"A001": 0.5, **{f"A{i:03d}": 0.10 for i in range(2, 7)}})
    returns = _returns(list(wv.weights.keys()))
    n = compute_portfolio_numerics(wv, returns)
    assert n.hhi == pytest.approx(0.30, abs=0.001)


def test_top1_and_top3():
    wv = _wv({"A001": 0.30, "A002": 0.20, "A003": 0.15, "A004": 0.20, "A005": 0.15})
    returns = _returns(list(wv.weights.keys()))
    n = compute_portfolio_numerics(wv, returns)
    assert n.top1_weight == 0.30
    assert n.top3_weight_sum == pytest.approx(0.70, abs=0.001)  # 0.30+0.20+0.20


def test_cluster_exposure():
    wv = _wv({"A001": 0.20, "A002": 0.20, "A003": 0.20, "A004": 0.20, "A005": 0.20})
    returns = _returns(list(wv.weights.keys()))
    clusters = [
        Cluster(cluster_id="c1", members=["A001", "A002"],
                avg_internal_correlation=0.8, category_label="x"),
        Cluster(cluster_id="c2", members=["A003", "A004"],
                avg_internal_correlation=0.7, category_label="y"),
    ]
    n = compute_portfolio_numerics(wv, returns, clusters=clusters)
    assert n.cluster_exposure["c1"] == pytest.approx(0.40, abs=0.001)
    assert n.cluster_exposure["c2"] == pytest.approx(0.40, abs=0.001)
    assert n.max_cluster_exposure == pytest.approx(0.40, abs=0.001)


def test_cvar_var_computed_for_long_returns():
    wv = _wv({"A001": 0.5, "A002": 0.5})
    rng = np.random.default_rng(42)
    n = 250
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    returns = pd.DataFrame(
        {"A001": rng.normal(0.0005, 0.02, n), "A002": rng.normal(0.0005, 0.02, n)},
        index=idx,
    )
    metrics = compute_portfolio_numerics(wv, returns)
    assert metrics.var_95_1d > 0  # 양수 (손실)
    assert metrics.cvar_95_1d >= metrics.var_95_1d  # CVaR ≥ VaR
    assert metrics.realized_vol_60d > 0


def test_short_history_zero_tail_metrics():
    wv = _wv({"A001": 1.0})
    returns = _returns(["A001"], n=30)  # < 100
    n = compute_portfolio_numerics(wv, returns)
    assert n.var_95_1d == 0.0
    assert n.cvar_95_1d == 0.0


def test_empty_weights():
    wv = WeightVector(method=OptimizationMethod.HRP, weights={"X": 1.0}, rationale="t")
    returns = pd.DataFrame()
    n = compute_portfolio_numerics(wv, returns)
    assert n.n_assets == 1
