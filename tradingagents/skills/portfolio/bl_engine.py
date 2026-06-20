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
                      growth_cap=0.70, mandate_cap=0.70):
    """max_quadratic_utility(mu, **prior Σ**, δ) + 그룹제약. 실패 시 None.

    MATH-1 불변식: 최적화 공분산은 호출자가 넘긴 prior Σ (절대 bl.bl_cov() 아님).

    mandate_cap = 0.70 = concentration_check.HARD_RISK_ASSET_CAP (대회 §2.2 위험자산 합 cap).
    예전 0.68 은 soft drift-trigger 값이라 틀렸음: growth_inflation baseline 의 risk-proxy(0.69)가
    0.68 에서 infeasible → no-view 에서 baseline 을 정확복원하지 못하고 0.049 off 로 밀렸음(MATH-1 위반).
    위험자산 cap 은 quadrant 무관하게 균일한 0.70 (recession 전용 lower cap 없음).
    growth_cap 도 0.70 유지: GROWTH_KEYS 합 ≤ 0.70 이 맞고 baseline 들의 growth 합은 ≤0.63.
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


def soft_clip(w, *, growth_keys, growth_cap=0.30, defensive_cap=0.50):
    """camp별 단일 버킷 천장 soft-clip + 잔여 water-fill (baseline 폴백 아님).

    성장 버킷 ≤ growth_cap, 방어 버킷 ≤ defensive_cap. 초과분을 비-clip 버킷에
    **현재 비중 비례**로 재분배(상대구조 보존), 각 수령자는 천장 head 로 clamp.
    """
    import pandas as pd
    w = w.copy().astype(float)
    cap = pd.Series({b: (growth_cap if b in growth_keys else defensive_cap) for b in w.index})
    # 천장 초과분을 한 번에 회수하고, 비례배분→head clamp 의 잔여를 loop 로 재순환.
    excess = float((w - cap).clip(lower=0.0).sum())
    w = w.clip(upper=cap)
    for _ in range(200):
        if excess < 1e-12:
            break
        room = (cap - w).clip(lower=0.0)
        elig = room > 1e-12
        base = float(w[elig].sum())
        if not bool(elig.any()) or base < 1e-12:
            break                      # no proportional recipients (all 0 or capped)
        add = (excess * (w.where(elig, 0.0) / base)).clip(upper=room)
        if float(add.sum()) < 1e-15:
            break
        w = w + add
        excess -= float(add.sum())     # carry head-clamp 잔여 forward
    return w
