"""NCO (Nested Clustered Optimization) — Lopez de Prado 2019.

Bucket 내부 종목들에 hierarchical clustering + intra/inter CVO 로 weight 결정.
Phase 3a 도입 — 기존 5 method 와 공존, A/B 테스트 가능.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)


# Phase 3a (2026-05-30). NCO algorithm constants.
NCO_MAX_NUM_CLUSTERS_RATIO: float = 0.5
NCO_MIN_NUM_CLUSTERS: int = 2
NCO_LINKAGE_METHOD: str = "single"
NCO_MIN_VAR_REGULARIZATION: float = 1e-8


def _opt_port(cov: pd.DataFrame, mu: pd.Series | None = None) -> pd.Series:
    """Closed-form CVO (long-only normalized).

    mu=None → min-var: w = (Σ + εI)^(-1) × 1 / (1^T (Σ + εI)^(-1) 1)
    mu given → max-sharpe: w = (Σ + εI)^(-1) × μ / (1^T (Σ + εI)^(-1) μ)

    음수 weight clip + 재정규화 (long-only).
    cov singular 시 equal weight fallback.
    """
    n = cov.shape[0]
    sigma_reg = cov.values + np.eye(n) * NCO_MIN_VAR_REGULARIZATION

    try:
        inv_sigma = np.linalg.inv(sigma_reg)
    except np.linalg.LinAlgError:
        return pd.Series(np.ones(n) / n, index=cov.index)

    if mu is None:
        w_raw = inv_sigma @ np.ones(n)
    else:
        w_raw = inv_sigma @ mu.reindex(cov.index).fillna(0.0).values

    w_clipped = np.maximum(w_raw, 0.0)
    w_sum = w_clipped.sum()
    if w_sum > 0:
        w = w_clipped / w_sum
    else:
        w = np.ones(n) / n

    return pd.Series(w, index=cov.index)


def _hierarchical_cluster(
    corr: pd.DataFrame,
    max_num_clusters: int,
) -> tuple[np.ndarray, float | None]:
    """Single-linkage clustering on √((1-corr)/2) distance.

    silhouette score 평가 후 best k 선택. 단일 cluster fallback 시 silhouette=None.
    """
    n = corr.shape[0]
    dist_matrix = np.sqrt(((1 - corr.values).clip(min=0)) / 2.0)
    np.fill_diagonal(dist_matrix, 0.0)
    cond_dist = squareform(dist_matrix, checks=False)
    Z = linkage(cond_dist, method=NCO_LINKAGE_METHOD)

    best_score = -np.inf
    best_labels = None
    for k in range(NCO_MIN_NUM_CLUSTERS, max_num_clusters + 1):
        labels = fcluster(Z, k, criterion="maxclust")
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(dist_matrix, labels, metric="precomputed")
        if score > best_score:
            best_score = score
            best_labels = labels

    if best_labels is None:
        return np.ones(n, dtype=int), None

    return best_labels, float(best_score)


def _intra_cluster_weights(
    cov: pd.DataFrame,
    labels: np.ndarray,
    mu: pd.Series | None = None,
) -> pd.DataFrame:
    """n_assets × n_clusters DataFrame.

    한 ticker (row) 는 자기 cluster (column) 에만 non-zero weight.
    """
    tickers = list(cov.index)
    unique_clusters = sorted(set(labels))
    intra = pd.DataFrame(0.0, index=tickers, columns=unique_clusters)

    for k in unique_clusters:
        members = [tickers[i] for i, lbl in enumerate(labels) if lbl == k]
        if len(members) == 1:
            intra.loc[members[0], k] = 1.0
            continue
        cov_sub = cov.loc[members, members]
        mu_sub = mu.reindex(members) if mu is not None else None
        w = _opt_port(cov_sub, mu_sub)
        intra.loc[members, k] = w.values

    return intra


def _inter_cluster_weights(
    reduced_cov: pd.DataFrame,
    reduced_mu: pd.Series | None = None,
) -> pd.Series:
    """Inter-cluster CVO."""
    return _opt_port(reduced_cov, reduced_mu)
