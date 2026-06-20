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


def implied_prior_returns(Sigma, w_baseline, delta):
    """Π = δ·Σ·w_baseline. δ-항등(MATH-2): 호출자는 최적화에도 같은 δ 사용."""
    import pandas as pd
    pi = delta * Sigma.values @ w_baseline.reindex(Sigma.index).values
    return pd.Series(pi, index=Sigma.index)


def _posterior_mu(Sigma, pi, P, Q, conf, delta):
    """μ_BL via pypfopt Idzorek. view 없으면(P 빈) prior pi 반환(정확복원 보장)."""
    import pandas as pd
    if P.shape[0] == 0:
        return pi.copy()
    try:
        from pypfopt.black_litterman import BlackLittermanModel
        bl = BlackLittermanModel(Sigma, pi=pi, P=P, Q=Q, omega="idzorek",
                                 view_confidences=conf, tau=TAU, risk_aversion=delta)
        # bl_returns() returns a pandas Series indexed by Sigma's columns.
        return pd.Series(np.asarray(bl.bl_returns()).ravel(), index=Sigma.index)
    except Exception as e:  # noqa: BLE001
        logger.warning("BL combine failed (%s) → prior μ", e)
        return pi.copy()


def _max_quad_utility(mu, Sigma, delta, growth_keys, mandate_risk_keys,
                      growth_cap=0.70, mandate_cap=0.68):
    """max_quadratic_utility(mu, **prior Σ**, δ) + 그룹제약. 실패 시 None.

    MATH-1 불변식: 최적화 공분산은 호출자가 넘긴 prior Σ (절대 bl.bl_cov() 아님).
    """
    try:
        import cvxpy as cp
        import pandas as pd
        from pypfopt import EfficientFrontier
        cols = list(Sigma.index)
        ef = EfficientFrontier(mu, Sigma, weight_bounds=(0, 1))
        if growth_keys:
            gi = [k for k, b in enumerate(cols) if b in growth_keys]
            if gi:
                ef.add_constraint(lambda w, gi=gi: cp.sum(w[gi]) <= growth_cap)
        if mandate_risk_keys:
            mi = [k for k, b in enumerate(cols) if b in mandate_risk_keys]
            if mi:
                ef.add_constraint(lambda w, mi=mi: cp.sum(w[mi]) <= mandate_cap)
        ef.max_quadratic_utility(risk_aversion=delta)
        cleaned = ef.clean_weights(rounding=None)  # OrderedDict
        return pd.Series([cleaned[c] for c in cols], index=cols)
    except Exception as e:  # noqa: BLE001
        logger.warning("MQU failed (%s)", e)
        return None


def bl_bucket_weights(Sigma, w_baseline, ranking, *, delta=2.5, base_spread=0.04,
                      growth_keys=None, mandate_risk_keys=None, extra_views=None):
    """전체 BL: Π 역산 → 상대view(+extra) → μ_BL → MQU(prior Σ). 실패 시 w_baseline."""
    import pandas as pd
    buckets = list(Sigma.index)
    w_baseline = w_baseline.reindex(buckets)
    pi = implied_prior_returns(Sigma, w_baseline, delta)
    P, Q, conf = build_relative_views(buckets, ranking, base_spread)
    if extra_views is not None:
        Pe, Qe, ce = extra_views
        if Pe.shape[0] > 0:
            P = np.vstack([P, Pe]) if P.shape[0] else Pe
            Q = np.concatenate([Q, Qe]) if Q.shape[0] else Qe
            conf = np.concatenate([conf, ce]) if conf.shape[0] else ce
    mu = _posterior_mu(Sigma, pi, P, Q, conf, delta)
    w = _max_quad_utility(mu, Sigma, delta, growth_keys or set(), mandate_risk_keys or set())
    if w is None or w.isna().any():
        return w_baseline.copy()
    return w


def _bl_weights_split_delta(Sigma, w_baseline, delta_inv, delta_opt):
    """음성 테스트 전용: 역산·최적화 δ 분리 시 복원 깨짐 입증(MATH-2 위반 데모)."""
    pi = implied_prior_returns(Sigma, w_baseline, delta_inv)
    w = _max_quad_utility(pi, Sigma, delta_opt, set(), set())
    return w if w is not None else w_baseline.copy()
