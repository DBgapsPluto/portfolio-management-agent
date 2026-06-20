"""Black-Litterman 버킷 배분 엔진.

prior 역산 (Π=δΣw_baseline, δ-항등) + 상대 view (tier 평균제거·P=e_i−1/N) +
Idzorek Ω + BL 결합 + max_quadratic_utility(**prior Σ**) + camp별 soft-clip.

핵심 불변식: view=∅ → 사후=prior=baseline 정확복원 (prior Σ 사용 시).
"""
from __future__ import annotations
import logging
import numpy as np

logger = logging.getLogger(__name__)

TAU = 0.05
CONVICTION_CAP = 0.95

_TIER_SCORE = {"strong_OW": 1.0, "OW": 0.5, "neutral": 0.0, "UW": -0.5, "strong_UW": -1.0}

def tier_scores(buckets: list[str], ranking: dict[str, tuple[str, float]]) -> np.ndarray:
    """tier·conviction → 부호화 점수 s_i, 평균제거(zero-sum). 미지정 버킷=neutral(0)."""
    raw = np.array([
        _TIER_SCORE.get((ranking.get(b) or ("neutral", 0.0))[0], 0.0)
        * min(max(float((ranking.get(b) or ("neutral", 0.0))[1]), 0.0), CONVICTION_CAP)
        for b in buckets
    ])
    return raw - raw.mean()

def build_relative_views(
    buckets: list[str], ranking: dict[str, tuple[str, float]], base_spread: float = 0.04,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """랭킹 → (P, Q, view_confidences). 비중립(s_i≠0) 버킷마다 P_i=e_i−1/N, Q_i=base_spread·s_i.

    전부 0(일색/중립) → 빈 (0×N, 0, 0) → 호출자가 view=∅ 처리.
    """
    n = len(buckets)
    s = tier_scores(buckets, ranking)
    active = [i for i in range(n) if abs(s[i]) > 1e-9]
    if not active:
        return np.zeros((0, n)), np.zeros(0), np.zeros(0)
    P = np.zeros((len(active), n))
    Q = np.zeros(len(active))
    conf = np.zeros(len(active))
    for row, i in enumerate(active):
        P[row, :] = -1.0 / n
        P[row, i] += 1.0
        Q[row] = base_spread * s[i]
        conf[row] = min(abs(s[i]), CONVICTION_CAP)
    return P, Q, conf
