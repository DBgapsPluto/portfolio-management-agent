"""NCO unit tests."""
import numpy as np
import pandas as pd
import pytest


def test_opt_port_min_var_uncorrelated_equal_weight():
    """Uncorrelated equal-vol → min-var = equal weight."""
    from tradingagents.skills.portfolio.nco import _opt_port

    cov = pd.DataFrame(
        np.eye(3) * 0.04, index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    w = _opt_port(cov)
    assert isinstance(w, pd.Series)
    assert list(w.index) == ["A", "B", "C"]
    # Equal weight ≈ 1/3
    for v in w.values:
        assert abs(v - 1/3) < 1e-6


def test_opt_port_min_var_different_vol_prefers_lower():
    """다른 vol → min-var 가 낮은 vol 우대."""
    from tradingagents.skills.portfolio.nco import _opt_port

    cov = pd.DataFrame(
        [[0.01, 0.0], [0.0, 0.16]],  # A vol=10%, B vol=40%
        index=["A", "B"], columns=["A", "B"],
    )
    w = _opt_port(cov)
    # A 가 더 큰 weight (낮은 vol)
    assert w["A"] > w["B"]
    # sum = 1
    assert abs(w.sum() - 1.0) < 1e-9


def test_opt_port_max_sharpe_with_mu():
    """mu given → max-sharpe path. 높은 mu / 낮은 vol 우대."""
    from tradingagents.skills.portfolio.nco import _opt_port

    cov = pd.DataFrame(
        np.eye(2) * 0.04, index=["A", "B"], columns=["A", "B"],
    )
    mu = pd.Series([0.1, 0.05], index=["A", "B"])
    w = _opt_port(cov, mu=mu)
    # A 가 더 큰 mu → 더 큰 weight
    assert w["A"] > w["B"]
    assert abs(w.sum() - 1.0) < 1e-9


def test_opt_port_handles_singular_cov():
    """Singular cov → equal weight fallback."""
    from tradingagents.skills.portfolio.nco import _opt_port

    # Rank-1 cov (perfectly correlated, singular)
    cov = pd.DataFrame(
        np.ones((3, 3)) * 0.04,  # 모든 원소 동일
        index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    w = _opt_port(cov)
    # equal weight fallback or regularized result — 모두 양수 + sum=1
    assert all(v > 0 for v in w.values)
    assert abs(w.sum() - 1.0) < 1e-9


def test_opt_port_negative_weights_clipped():
    """음수 weight 발생 시 clip + 재정규화."""
    from tradingagents.skills.portfolio.nco import _opt_port

    # Negative correlation 으로 음수 weight 유도 가능
    cov = pd.DataFrame(
        [[0.04, -0.03], [-0.03, 0.04]],
        index=["A", "B"], columns=["A", "B"],
    )
    w = _opt_port(cov)
    assert all(v >= 0 for v in w.values)
    assert abs(w.sum() - 1.0) < 1e-9
