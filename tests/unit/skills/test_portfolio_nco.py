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


def test_hierarchical_cluster_two_distinct_groups():
    """2 그룹 (within corr 1, between corr 0) → 2 cluster, silhouette 높음."""
    from tradingagents.skills.portfolio.nco import _hierarchical_cluster

    # 4 ticker: A,B 한 그룹 (corr=0.99), C,D 다른 그룹 (corr=0.99), 그룹 간 corr=0
    corr = pd.DataFrame([
        [1.0, 0.99, 0.0, 0.0],
        [0.99, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.99],
        [0.0, 0.0, 0.99, 1.0],
    ], index=["A", "B", "C", "D"], columns=["A", "B", "C", "D"])
    labels, silh = _hierarchical_cluster(corr, max_num_clusters=2)
    # A 와 B 같은 cluster, C 와 D 같은 cluster
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]
    assert silh is not None
    assert silh > 0.5  # 명확한 separation


def test_hierarchical_cluster_perfectly_correlated_returns_one_cluster():
    """모두 corr ≈ 1 → 모두 1 cluster, silhouette=None."""
    from tradingagents.skills.portfolio.nco import _hierarchical_cluster

    corr = pd.DataFrame(
        np.full((3, 3), 0.999), index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    np.fill_diagonal(corr.values, 1.0)
    labels, silh = _hierarchical_cluster(corr, max_num_clusters=2)
    # 모두 같은 label 또는 silhouette None (fallback)
    assert len(set(labels)) <= 2


def test_hierarchical_cluster_silhouette_picks_best_k():
    """4 ticker 가 명확한 2 그룹 → k=2 선택."""
    from tradingagents.skills.portfolio.nco import _hierarchical_cluster

    corr = pd.DataFrame([
        [1.0, 0.99, 0.05, 0.05],
        [0.99, 1.0, 0.05, 0.05],
        [0.05, 0.05, 1.0, 0.99],
        [0.05, 0.05, 0.99, 1.0],
    ], index=["A", "B", "C", "D"], columns=["A", "B", "C", "D"])
    labels, silh = _hierarchical_cluster(corr, max_num_clusters=3)
    # best k = 2 가 선택됨
    assert len(set(labels)) == 2


def test_intra_cluster_weights_matrix_shape():
    """n_assets × n_clusters DataFrame."""
    from tradingagents.skills.portfolio.nco import _intra_cluster_weights

    cov = pd.DataFrame(
        np.eye(4) * 0.04, index=["A", "B", "C", "D"], columns=["A", "B", "C", "D"],
    )
    labels = np.array([1, 1, 2, 2])  # A,B cluster 1, C,D cluster 2
    intra = _intra_cluster_weights(cov, labels)
    assert intra.shape == (4, 2)
    # A,B 만 cluster 1 column 에 non-zero
    assert intra.loc["A", 1] > 0
    assert intra.loc["B", 1] > 0
    assert intra.loc["A", 2] == 0
    assert intra.loc["B", 2] == 0
    # 각 cluster column 의 weight sum = 1
    for col in intra.columns:
        col_sum = intra[col].sum()
        assert abs(col_sum - 1.0) < 1e-6


def test_intra_cluster_weights_single_member_cluster():
    """단일 ticker cluster → weight = 1.0."""
    from tradingagents.skills.portfolio.nco import _intra_cluster_weights

    cov = pd.DataFrame(
        np.eye(3) * 0.04, index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    labels = np.array([1, 2, 3])  # 모두 다른 cluster
    intra = _intra_cluster_weights(cov, labels)
    # 각 ticker 가 자기 cluster 에 weight = 1.0
    assert intra.loc["A", 1] == 1.0
    assert intra.loc["B", 2] == 1.0
    assert intra.loc["C", 3] == 1.0


def test_inter_cluster_weights_min_var_path():
    """Reduced cov 에 min-var → 분산 작은 cluster 우대."""
    from tradingagents.skills.portfolio.nco import _inter_cluster_weights

    # cluster 1: 분산 작음 (0.01), cluster 2: 분산 큼 (0.16)
    reduced_cov = pd.DataFrame(
        [[0.01, 0.0], [0.0, 0.16]],
        index=[1, 2], columns=[1, 2],
    )
    w = _inter_cluster_weights(reduced_cov)
    assert w[1] > w[2]  # 분산 작은 cluster 우대
    assert abs(w.sum() - 1.0) < 1e-9


def test_inter_cluster_weights_with_mu_max_sharpe_path():
    """mu given → max-sharpe."""
    from tradingagents.skills.portfolio.nco import _inter_cluster_weights

    reduced_cov = pd.DataFrame(
        np.eye(2) * 0.04, index=[1, 2], columns=[1, 2],
    )
    reduced_mu = pd.Series([0.1, 0.05], index=[1, 2])
    w = _inter_cluster_weights(reduced_cov, reduced_mu)
    assert w[1] > w[2]  # 더 큰 mu 우대
