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


TURNOVER_CAP = 0.35  # ||w − w_baseline||₁ 상한: 단일 view 가 정책 baseline 을 통째로
                     # 뒤집지 못하게 하는 trade-거리 한도(view 는 baseline 을 흔들 뿐 대체 아님).


def _max_quad_utility(mu, Sigma, delta, growth_keys, mandate_risk_keys,
                      growth_cap=0.70, mandate_cap=0.70, w_baseline=None,
                      turnover_cap=TURNOVER_CAP):
    """max_quadratic_utility(mu, **prior Σ**, δ) + 그룹제약 + turnover 제약. 실패 시 None.

    MATH-1 불변식: 최적화 공분산은 호출자가 넘긴 prior Σ (절대 bl.bl_cov() 아님).

    mandate_cap = 0.70 = concentration_check.HARD_RISK_ASSET_CAP (대회 §2.2 위험자산 합 cap).
    예전 0.68 은 soft drift-trigger 값이라 틀렸음: growth_inflation baseline 의 risk-proxy(0.69)가
    0.68 에서 infeasible → no-view 에서 baseline 을 정확복원하지 못하고 0.049 off 로 밀렸음(MATH-1 위반).
    위험자산 cap 은 quadrant 무관하게 균일한 0.70 (recession 전용 lower cap 없음).
    growth_cap 도 0.70 유지: GROWTH_KEYS 합 ≤ 0.70 이 맞고 baseline 들의 growth 합은 ≤0.63.

    turnover 제약(BLOW-1 후속): ||w−w_baseline||₁ ≤ turnover_cap. 미지정(w_baseline=None)
    이면 생략. baseline 에서 turnover=0 은 항상 feasible 이라 no-view 정확복원(MATH-1)은
    불변. 강한 단일 view 에서 MQU 가 2-자산 코너로 튀어 portfolio 를 통째로 뒤집던 것을
    막는다(soft_clip 천장만으론 turnover 가 무한정 커질 수 있었음).
    """
    try:
        import cvxpy as cp
        import numpy as np
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
        if w_baseline is not None and turnover_cap is not None:
            wb = np.asarray(w_baseline.reindex(cols).fillna(0.0).values, dtype=float)
            ef.add_constraint(lambda w, wb=wb, tc=float(turnover_cap): cp.norm1(w - wb) <= tc)
        ef.max_quadratic_utility(risk_aversion=delta)
        cleaned = ef.clean_weights(rounding=None)  # OrderedDict
        return pd.Series([cleaned[c] for c in cols], index=cols)
    except Exception as e:  # noqa: BLE001
        logger.warning("MQU failed (%s)", e)
        return None


def bl_bucket_weights(Sigma, w_baseline, ranking, *, delta=2.5, base_spread=0.04,
                      growth_keys=None, mandate_risk_keys=None, extra_views=None,
                      growth_cap=0.70, mandate_cap=0.70, turnover_cap=TURNOVER_CAP):
    """전체 BL: Π 역산 → 상대view(+extra) → μ_BL → MQU(prior Σ). 실패 시 w_baseline.

    growth_cap/mandate_cap 은 GROUP 제약(GROWTH_KEYS 합·mandate risk 합 ≤ cap)으로
    _max_quad_utility 에 그대로 전달된다. 부분핀 서브문제에서는 호출자(bl_allocate)가
    예산-인지(budget-aware) 캡을 계산해 넘긴다(전체 0.70 mandate 를 서브벡터로 환산).
    """
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
    w = _max_quad_utility(mu, Sigma, delta, growth_keys or set(), mandate_risk_keys or set(),
                          growth_cap=growth_cap, mandate_cap=mandate_cap,
                          w_baseline=w_baseline, turnover_cap=turnover_cap)
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
    # 천장 초과분을 한 번에 회수(excess)하고, head clamp 로 미흡수된 잔여를 loop 로 재순환한다.
    # 비례배분의 수령자가 전부 0-비중이면(코너해) 비중비례 워터필이 바닥나 합이 target
    # 미만으로 남는다 → 그 경우 head room 비례로 폴백해 잔여를 흡수, 합을 보존한다(BLOW-1).
    excess = float((w - cap).clip(lower=0.0).sum())
    w = w.clip(upper=cap)
    for _ in range(200):
        if excess < 1e-12:
            break
        room = (cap - w).clip(lower=0.0)
        elig = room > 1e-12
        cur = w.where(elig, 0.0)
        if float(cur.sum()) > 1e-12:
            dist_w = cur                    # 현재 비중 비례(상대구조 보존)
        else:
            dist_w = room.where(elig, 0.0)  # 수령자가 전부 0-비중 → head room 비례로 채움
        denom = float(dist_w.sum())
        if denom < 1e-12:
            break                           # 진짜로 capacity 소진(합이 target 미만 잔존)
        add = (excess * dist_w / denom).clip(upper=room)
        if float(add.sum()) < 1e-15:
            break
        w = w + add
        excess -= float(add.sum())          # head-clamp 미흡수 잔여 carry forward
    return w


def bl_allocate(Sigma, w_baseline, ranking, *, pinned=None, delta=2.5, base_spread=0.04,
                growth_keys=None, mandate_risk_keys=None, extra_views=None,
                growth_cap=0.30, defensive_cap=0.50, turnover_cap=TURNOVER_CAP):
    """BL 배분 오케스트레이터: 부분실패 버킷핀 + (14−k) BL + soft-clip + attribution meta.

    반환 {weights: pd.Series(14), meta: {bucket: {status,...}, __global__: {...}}}.
    status: bl | baseline_pinned | full_fallback.

    핀 버킷은 정확히 w_baseline[b] 로 고정, 나머지는 잔여예산(1−Σpinned)에서 BL.
    BL 서브벡터에만 soft-clip → budget 스케일 → budget 으로 재정규화(핀은 그대로).
    Σ 비거나 핀이 절반 이상이면 전체 baseline 폴백.
    """
    import pandas as pd
    pinned = set(pinned or [])
    all_buckets = list(w_baseline.index)
    meta: dict = {}

    if Sigma is None or Sigma.empty or len(pinned) >= (len(all_buckets) + 1) // 2:
        meta["__global__"] = {"status": "full_fallback", "reason": "empty_sigma_or_majority_pinned"}
        return {"weights": w_baseline.copy(), "meta": meta}

    bl_buckets = [b for b in all_buckets if b not in pinned]
    pin_weight = float(w_baseline[list(pinned)].sum()) if pinned else 0.0
    budget = 1.0 - pin_weight

    Sigma_bl = Sigma.reindex(index=bl_buckets, columns=bl_buckets)
    base_bl = w_baseline[bl_buckets]
    base_bl = base_bl / base_bl.sum() if base_bl.sum() > 0 else base_bl

    gk = {b for b in (growth_keys or set()) if b in bl_buckets}
    mk = {b for b in (mandate_risk_keys or set()) if b in bl_buckets}
    rk = {k: v for k, v in ranking.items() if k in bl_buckets}

    # 예산-인지(budget-aware) GROUP 캡: mandate 는 TOTAL(post-budget) 비중에 걸린다.
    # total_growth = sub_growth×budget + pinned_growth ≤ HARD_RISK ⇒
    #   g_cap_sub = (HARD_RISK − pinned_growth) / budget (mandate 동일).
    # 핀이 없으면 budget=1, pinned_*=0 → caps=0.70 = full-vector 거동과 동일(gate-2 불변).
    HARD_RISK = 0.70  # = concentration_check.HARD_RISK_ASSET_CAP
    pinned_growth = sum(float(w_baseline[b]) for b in pinned if b in (growth_keys or set()))
    pinned_mandate = sum(float(w_baseline[b]) for b in pinned if b in (mandate_risk_keys or set()))
    g_cap_sub = min(1.0, (HARD_RISK - pinned_growth) / budget) if budget > 1e-9 else 1.0
    m_cap_sub = min(1.0, (HARD_RISK - pinned_mandate) / budget) if budget > 1e-9 else 1.0

    w_bl = bl_bucket_weights(Sigma_bl, base_bl, rk, delta=delta, base_spread=base_spread,
                             growth_keys=gk, mandate_risk_keys=mk, extra_views=extra_views,
                             growth_cap=g_cap_sub, mandate_cap=m_cap_sub,
                             turnover_cap=turnover_cap)
    # 1) MQU 해의 합이 solver tolerance 로 1 에서 미세이탈할 수 있으므로 먼저 budget 으로
    #    재정규화한다(서브벡터를 정확히 budget 합으로 맞춤, 핀 버킷은 baseline 고정 유지).
    # 2) 그 다음 soft-clip 으로 천장을 최종 스케일된 벡터에 강제한다. soft_clip 이
    #    합-보존(BLOW-1)이라 budget 은 유지되고, renorm 의 ×(budget/bl_sum) 스케일업이
    #    at-cap 버킷을 천장 위로 재팽창시키는 일이 없다(budget≤1).
    bl_sum = float(w_bl.sum())
    w_bl = (w_bl / bl_sum * budget) if bl_sum > 0 else w_bl
    w_bl = soft_clip(w_bl, growth_keys=gk, growth_cap=growth_cap, defensive_cap=defensive_cap)

    out = pd.Series(0.0, index=all_buckets)
    for b in bl_buckets:
        out[b] = float(w_bl.get(b, 0.0))
        meta[b] = {"status": "bl"}
    for b in pinned:
        out[b] = float(w_baseline[b])
        meta[b] = {"status": "baseline_pinned"}
    glob = {"status": "bl", "n_pinned": len(pinned)}
    if pinned:
        # 핀이 있으면 예산·서브캡을 기록 → attribution 투명성(서브문제가 어떤 캡으로 풀렸는지).
        glob.update({"budget": round(budget, 6),
                     "growth_cap_sub": round(g_cap_sub, 6),
                     "mandate_cap_sub": round(m_cap_sub, 6)})
    meta["__global__"] = glob
    return {"weights": out, "meta": meta}
