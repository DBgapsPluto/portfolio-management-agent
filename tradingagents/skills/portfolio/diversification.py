"""Effective Number of Bets (ENB) via Minimum-Linear-Torsion.

Phase 1 도입. Meucci-Santangelo-Deguest 2015 의 minimum-linear-torsion 으로
포트폴리오 분산을 비상관 factor 들로 분해한 뒤 entropy-based ENB 계산.
"""
from __future__ import annotations

import logging
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ENB_NUMERICAL_FLOOR: float = 1e-12


def _matrix_inv_sqrt(A: np.ndarray) -> np.ndarray:
    """대칭 행렬의 역제곱근. 음수 eigenvalue 는 클립 + WARNING."""
    vals, vecs = np.linalg.eigh(A)
    n_clipped = int(np.sum(vals < ENB_NUMERICAL_FLOOR))
    if n_clipped > 0:
        logger.warning(
            "non-PSD matrix: %d/%d eigenvalues < %.0e — clipping",
            n_clipped, len(vals), ENB_NUMERICAL_FLOOR,
        )
    vals_clipped = np.maximum(vals, ENB_NUMERICAL_FLOOR)
    return vecs @ np.diag(1.0 / np.sqrt(vals_clipped)) @ vecs.T


def minimum_torsion_matrix(sigma: np.ndarray) -> np.ndarray:
    """T such that T Σ Tᵀ = diag(diag(Σ)).

    Closed form (Meucci-Santangelo-Deguest 2015):
        T = D^(1/2) × C^(-1/2) × D^(-1/2)
    where D = diag(diag(Σ)), C = D^(-1/2) Σ D^(-1/2).
    """
    if not np.allclose(sigma, sigma.T, atol=1e-12):
        raise ValueError(
            f"covariance matrix must be symmetric; "
            f"max asymmetry: {np.max(np.abs(sigma - sigma.T)):.3e}"
        )
    diag_var = np.diag(sigma)
    if np.any(diag_var <= 0):
        raise ValueError(
            f"non-positive diagonal in covariance: min={diag_var.min():.3e}"
        )
    D_sqrt = np.diag(np.sqrt(diag_var))
    D_inv_sqrt = np.diag(1.0 / np.sqrt(diag_var))
    C = D_inv_sqrt @ sigma @ D_inv_sqrt
    C_inv_sqrt = _matrix_inv_sqrt(C)
    return D_sqrt @ C_inv_sqrt @ D_inv_sqrt


def minimum_torsion_decomposition(w: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """반환 p_i: 비상관 factor i 의 분산 기여 (합 1).

    e = T^(-T) w   (exposures, n-vector)
    factor_var_i = e_i² × diag(Σ)_i
    p_i = factor_var_i / (w^T Σ w)
    """
    n = len(w)
    if n == 1:
        return np.array([1.0])
    T = minimum_torsion_matrix(sigma)
    exposures = np.linalg.solve(T.T, w)
    diag_var = np.diag(sigma)
    factor_var = exposures ** 2 * diag_var
    port_var = float(w @ sigma @ w)
    if port_var <= ENB_NUMERICAL_FLOOR:
        return np.full(n, 1.0 / n)
    p = factor_var / port_var
    p = np.maximum(p, 0.0)
    s = p.sum()
    return p / s if s > 0 else np.full(n, 1.0 / n)


def compute_enb(
    weights: dict[str, float] | pd.Series,
    sigma: pd.DataFrame,
    method: Literal["minimum_torsion", "pca"] = "minimum_torsion",
) -> float:
    """ENB = exp(-Σ p_i ln p_i)."""
    raise NotImplementedError
