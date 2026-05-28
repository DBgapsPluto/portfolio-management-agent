"""Effective Number of Bets (ENB) via Minimum-Linear-Torsion.

Phase 1 도입. Meucci-Santangelo-Deguest 2015 의 minimum-linear-torsion 으로
포트폴리오 분산을 비상관 factor 들로 분해한 뒤 entropy-based ENB 계산.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

ENB_NUMERICAL_FLOOR: float = 1e-12


def _matrix_inv_sqrt(A: np.ndarray) -> np.ndarray:
    """대칭 행렬의 역제곱근. 음수 eigenvalue 는 ENB_NUMERICAL_FLOOR 로 클립."""
    raise NotImplementedError


def minimum_torsion_matrix(sigma: np.ndarray) -> np.ndarray:
    """T such that T Σ Tᵀ = diag(diag(Σ))."""
    raise NotImplementedError


def minimum_torsion_decomposition(w: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """반환: p_i 분포 (합 1, 음수 자산 비상관 factor 분산 기여)."""
    raise NotImplementedError


def compute_enb(
    weights: dict[str, float] | pd.Series,
    sigma: pd.DataFrame,
    method: Literal["minimum_torsion", "pca"] = "minimum_torsion",
) -> float:
    """ENB = exp(-Σ p_i ln p_i)."""
    raise NotImplementedError
