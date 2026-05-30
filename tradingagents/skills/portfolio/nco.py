"""NCO (Nested Clustered Optimization) — Lopez de Prado 2019.

Bucket 내부 종목들에 hierarchical clustering + intra/inter CVO 로 weight 결정.
Phase 3a 도입 — 기존 5 method 와 공존, A/B 테스트 가능.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

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
