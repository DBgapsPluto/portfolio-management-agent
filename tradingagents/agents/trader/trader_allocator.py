"""Stage 3 trader/allocator — LLM step A(버킷 비중) + 결정론 step B(종목 선정) + AUM 종목내 배분.

step A: quadrant 앵커 baseline 대비 버킷별 tilt 결정 (BucketTilt) → 밴드 투영
step B: 비중>0 버킷의 종목 선정 (결정론 — select_representative_candidates)
종목내 비중: AUM 가중 + 단일 20% cap (within_bucket.aum_weighted_allocation)

위험자산(≤70%, 대회 §2.2)은 RISK_BUCKET_NAMES{kr_equity·global_equity·precious_metals·
cyclical_commodity_fx} 기준 — 출력 직전 repair_risk_cap 으로 결정론 보장, Stage 5 가 하드 검증.
(universe per-ETF 위험/안전 플래그는 종목 분류 보조용 — 70% mandate 와 별개.)
"""
from __future__ import annotations
import json
import logging
import math
from datetime import date
from pathlib import Path

from tradingagents.dataflows.universe import Universe
from tradingagents.agents.utils.structured import bind_structured, invoke_structured_obj
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod, BucketTilt,
)
from tradingagents.skills.portfolio.candidate_selector import (
    select_representative_candidates, HETEROGENEOUS_BUCKETS,
)
from tradingagents.skills.portfolio.factor_scorer import risk_adjusted_momentum
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, BUCKET_KR_NAME, GROWTH_KEYS,
)
from tradingagents.backtest.bucket_proxies import fetch_bucket_proxy_returns
from tradingagents.skills.portfolio.bucket_cov import bucket_covariance
from tradingagents.skills.portfolio import bl_engine
from tradingagents.skills.portfolio.within_bucket import (
    aggregate_weights_to_buckets, aum_weighted_allocation,
    momentum_weighted_allocation,
    drop_negligible_holdings, InfeasibleBucket, SINGLE_CAP,
)
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band, effective_band, project_to_band,
    apply_macro_modifiers,
)
from tradingagents.skills.portfolio.vol_haircut import (
    bucket_volatility, apply_vol_haircut,
)
from tradingagents.skills.mandate.risk_repair import repair_risk_cap
from tradingagents.skills.mandate.category_repair import repair_category_caps
from tradingagents.skills.mandate.cluster_repair import repair_cluster_cap
from tradingagents.skills.mandate.concentration_check import RISK_BUCKET_NAMES, CATEGORY_CAPS
from tradingagents.skills.portfolio.sub_category import bucket_for_etf

logger = logging.getLogger(__name__)

# 실행상 무의미한 극소액 잔여(성과 기여 < 거래비용)의 비중 하한. 이 미만 종목은
# 정리하고 재분배 — 단 '비율 컷오프'가 아니라 잔여만 (분산 소액 2~5%는 보존).
# portfolio_dials["min_holding_weight"] 로 런타임 조정 가능.
NEGLIGIBLE_FLOOR: float = 0.01

# category/risk/cluster repair 교대 반복 횟수. cluster_repair 의 water-fill 이
# category-capped 종목에 mass 를 흘려 cap 을 재위반할 수 있어, cluster 도 루프
# '안'에서 교대시켜 매 패스마다 category/risk 가 재정리하도록 한다. 잔차는 기하급수로
# 줄지만 다중 클러스터+다중 category 가 동시에 binding 인 feasible 케이스는 6회로도
# validator FLOAT_TOLERANCE(1e-6) 를 넘을 수 있어(적대감사 확인) 12회로 둔다 — water-fill
# 은 싸므로 비용 무시 가능, 미수렴 잔차는 Stage 5 validator 가 동일 임계로 최종 차단.
_REPAIR_ITERS: int = 12


def _repair_all_weights(w, cat_of, category_caps, is_risk, clusters):
    """category·risk·cluster cap 을 동시 만족하도록 결정론 repair 후 renormalize.

    세 repair 는 서로 직교하지 않는다 — cluster_repair 가 freed mass 를 비-군집
    종목에 water-fill 하면 그 종목의 category 합이 cap 을 넘을 수 있다. 그래서
    cluster_repair 를 루프 '밖'에서 한 번만 돌리면(category 가 그 뒤를 못 닦아)
    category cap 이 재위반된다. 세 repair 를 교대 반복하면 상호작용이 수렴한다
    (잔차 기하급수 감소). 최종 hard 판정은 Stage 5 validator 가 동일 임계로 수행.
    """
    for _ in range(_REPAIR_ITERS):
        w = repair_category_caps(w, cat_of, category_caps)
        w = repair_risk_cap(w, is_risk)
        w = repair_cluster_cap(w, clusters, cap=0.35)
    s = sum(w.values())
    return {t: x / s for t, x in w.items()} if s > 0 else w


def _load_universe(path: str) -> Universe:
    return Universe(**json.loads(Path(path).read_text()))


def _pool_by_bucket(uni: Universe) -> dict[str, list]:
    pool: dict[str, list] = {k: [] for k in GAPS_BUCKET_KEYS}
    for e in uni.etfs:
        if e.gaps_bucket in pool:
            pool[e.gaps_bucket].append(e)
    return pool


_VALID_QUADRANTS = set(QUADRANT_BASELINE)
_DEFAULT_QUADRANT = "growth_disinflation"   # macro degraded default 와 일치
_DEGRADED_CONFIDENCE = 0.1


def _resolve_quadrant(state) -> str:
    mr = state.get("macro_report")
    q = getattr(getattr(mr, "regime", None), "quadrant", None)
    return q if q in _VALID_QUADRANTS else _DEFAULT_QUADRANT


def _resolve_confidence(state) -> float:
    mr = state.get("macro_report")
    c = getattr(getattr(mr, "regime", None), "confidence", None)
    return float(c) if isinstance(c, (int, float)) else _DEGRADED_CONFIDENCE


def _resolve_fx_regime(state) -> str:
    mr = state.get("macro_report")
    return getattr(getattr(mr, "fx", None), "regime", None) or "neutral"


def _resolve_credit_regime(state) -> str:
    mr = state.get("macro_report")
    return getattr(getattr(mr, "financial_conditions", None), "regime", None) or "neutral"


_STEP_A_SYSTEM = (
    "당신은 자산배분 트레이더다. 주어진 'regime 앵커(baseline)'에서 출발해, "
    "리서치 판단으로 버킷별 tilt(앵커 대비 가감)만 결정한다. 다음 순서로 사고하라:\n"
    "① 리스크 예산: risk_tilt·regime 으로 위험자산 총량 방향(앵커가 이미 ≤70% 지향).\n"
    "② 방어(A1~A5): regime 따라 cash/듀레이션/금·인플레 가감.\n"
    "③ 성장(B1~B9): thesis·key_risks 로 버킷 tilt.\n"
    "   이종(heterogeneous) 버킷(b2_dm_core·b3_global_tech·b5_other_intl)은 추가로 "
    "sub_category 선호도(sub_category_views)를 value/momentum/news 테마 신호로 출력하라 "
    "— +선호 / −배제 / 0중립, 범위 [-1,+1]. 그 외 버킷은 sub_category_views 를 비워둔다.\n"
    "④ 자가검증: tilt 는 허용밴드 내, 오버웨이트는 언더웨이트로 펀딩(net≈0).\n"
    "벗어나지 않을 버킷은 tilt 를 생략(=0)하라."
)


_STEP_A_SYSTEM_BL = (
    "당신은 자산배분 트레이더다. 14개 버킷을 매력도 tier 로 상대순위 매겨라:\n"
    "각 버킷에 tier ∈ {strong_OW, OW, neutral, UW, strong_UW} 와 conviction(0~0.95) 부여.\n"
    "절대 수익률을 예측하지 말고 버킷 간 '상대 매력도 순서'만 판단하라.\n"
    "확신 없는 버킷은 neutral. 모두 같은 tier(일색)는 금지 — 상대순위가 의미 없어진다.\n"
    "이종 버킷(b2_dm_core·b3_global_tech·b5_other_intl)은 sub_category_views 도 함께 출력하라."
)


def _ranking_from_tilt(bt) -> dict:
    """BucketTilt.bucket_ranking → bl_engine 포맷 {bucket: (tier, conviction)}."""
    return {k: (v.tier, float(v.conviction))
            for k, v in (getattr(bt, "bucket_ranking", None) or {}).items()}


def _step_a_prompt_bl(state, quadrant, fx_regime, credit_regime, het_candidates=None):
    """BL 상대순위 Step A 프롬프트 — tilt(밴드) 대신 bucket_ranking(tier+conviction)."""
    rd = state.get("research_decision")
    thesis = getattr(rd, "thesis_md", "") if rd else ""
    key_risks = getattr(rd, "key_risks", []) if rd else []
    bucket_list = "\n".join(f"  {b} ({BUCKET_KR_NAME[b]})" for b in GAPS_BUCKET_KEYS)
    het_block = ""
    if het_candidates:
        het_block = "\n## 이종 버킷 sub_category 후보\n" + _render_het_candidates(het_candidates) + "\n"
    body = (
        f"## Regime: {quadrant}, fx: {fx_regime}, credit: {credit_regime}\n\n"
        f"## 14 버킷 (각각 tier+conviction 상대순위 부여)\n{bucket_list}\n"
        f"{het_block}\n"
        f"## 리서치 종합\n{thesis}\n\n"
        f"## 핵심 리스크\n" + ("\n".join(f"  - {r}" for r in key_risks) or "  (없음)") + "\n\n"
        f"## Stage1 요약\n매크로: {state.get('macro_summary','(없음)')}\n"
        f"리스크: {state.get('risk_summary','(없음)')}\n뉴스: {state.get('news_summary','(없음)')}\n\n"
        "각 버킷의 tier+conviction 을 bucket_ranking 으로, 이종 버킷 선호를 sub_category_views 로 출력하라."
    )
    return [{"role": "system", "content": _STEP_A_SYSTEM_BL},
            {"role": "user", "content": body}]


def _heterogeneous_subcat_candidates(pool, sub_cat, aum, momentum) -> dict[str, list[dict]]:
    """이종 버킷별 sub_category 요약 — LLM 이 sub_category_views 를 낼 근거.

    버킷 → [{sub_cat, n, aum_krw(합), momentum(평균)}] (모멘텀 desc). momentum 이 -inf
    (패널 없음)인 경우 None 으로 노출. 동질 버킷은 제외.
    """
    out: dict[str, list[dict]] = {}
    for bkey in HETEROGENEOUS_BUCKETS:
        groups: dict[str, list[str]] = {}
        for e in pool.get(bkey, []):
            sc = sub_cat.get(e.ticker) or "(unlabeled)"
            groups.setdefault(sc, []).append(e.ticker)
        if not groups:
            continue
        rows = []
        for sc, tickers in groups.items():
            moms = [momentum.get(t) for t in tickers
                    if momentum.get(t) not in (None, float("-inf"))]
            rows.append({
                "sub_category": sc,
                "n": len(tickers),
                "aum_krw": sum(aum.get(t, 0.0) for t in tickers),
                "momentum": (sum(moms) / len(moms)) if moms else None,
            })
        rows.sort(key=lambda r: (r["momentum"] if r["momentum"] is not None else float("-inf")),
                  reverse=True)
        out[bkey] = rows
    return out


def _render_het_candidates(het_candidates) -> str:
    """이종 버킷 sub_category 후보를 프롬프트용 짧은 텍스트로 — 버킷별 1~N 줄."""
    if not het_candidates:
        return ""
    lines = []
    for bkey, rows in het_candidates.items():
        kr = BUCKET_KR_NAME.get(bkey, bkey)
        lines.append(f"  {bkey} ({kr}):")
        for r in rows:
            mom = f"{r['momentum']:+.2f}" if r["momentum"] is not None else "n/a"
            lines.append(
                f"    - {r['sub_category']}: n={r['n']}, "
                f"AUM {r['aum_krw']/1e8:.0f}억, mom {mom}"
            )
    return "\n".join(lines)


def _step_a_prompt(state, quadrant, risk_tilt, fx_regime, credit_regime, confidence,
                   anchor, eff, het_candidates=None) -> list[dict]:
    rd = state.get("research_decision")
    thesis = getattr(rd, "thesis_md", "") if rd else ""
    key_risks = getattr(rd, "key_risks", []) if rd else []
    fb = state.get("allocation_feedback") or []
    fb_txt = "\n".join(f"  - {getattr(v, 'message', str(v))}" for v in fb)

    anchor_lines = "\n".join(
        f"  {b} ({BUCKET_KR_NAME[b]}): base {anchor[b]:.2f} "
        f"허용[{eff[b][0]:.2f}, {eff[b][1]:.2f}]"
        for b in GAPS_BUCKET_KEYS
    )
    het_txt = _render_het_candidates(het_candidates)
    body = (
        f"## Regime: {quadrant} / risk_tilt: {risk_tilt} "
        f"(confidence {confidence:.2f}), fx: {fx_regime}, credit: {credit_regime}\n\n"
        f"## 앵커 baseline + 허용밴드 (이 안에서만 tilt)\n{anchor_lines}\n\n"
        + (f"## 이종 버킷 sub_category 후보 (선호/배제 view 대상)\n{het_txt}\n\n" if het_txt else "")
        + f"## 리서치 종합\n{thesis}\n\n"
        f"## 핵심 리스크\n" + ("\n".join(f"  - {r}" for r in key_risks) or "  (없음)") + "\n\n"
        f"## Stage1 요약\n"
        f"매크로: {state.get('macro_summary','(없음)')}\n"
        f"리스크: {state.get('risk_summary','(없음)')}\n"
        f"기술적: {state.get('technical_summary','(없음)')}\n"
        f"뉴스: {state.get('news_summary','(없음)')}\n\n"
        + (f"## 직전 위반 피드백 (반영 필수)\n{fb_txt}\n\n" if fb_txt else "")
        + "각 버킷의 tilt(앵커 대비 가감)를 출력하라. 0 인 버킷은 생략.\n"
        + "이종 버킷(b2/b3/b5)은 위 sub_category 후보에 대해 sub_category_views "
        "(+선호/−배제/0중립, [-1,+1])도 함께 출력하라."
    )
    return [
        {"role": "system", "content": _STEP_A_SYSTEM},
        {"role": "user", "content": body},
    ]


def _clamp_to_pool_capacity(
    bucket_weights: dict[str, float], pool: dict[str, list]
) -> dict[str, float]:
    """각 버킷을 n_pool * SINGLE_CAP 용량으로 clamp, 초과분은 여유 버킷에 water-fill 재배분.

    어느 버킷도 자기 풀 용량을 넘지 않게 한다(전체 용량<1 이면 합<1 가능, 미배분 잔여).
    """
    cap = {k: len(pool.get(k, [])) * SINGLE_CAP for k in bucket_weights}
    clamped = {k: min(w, cap[k]) for k, w in bucket_weights.items()}
    overflow = sum(bucket_weights.values()) - sum(clamped.values())
    # 최대 ~2회: 1회 fill 후 overflow≤ε 또는 room=0 으로 수렴
    while overflow > 1e-9:
        head = {k: cap[k] - clamped[k] for k in clamped}
        room = sum(v for v in head.values() if v > 0)
        if room <= 1e-9:
            break
        moved = min(overflow, room)
        for k in clamped:
            if head[k] > 0:
                clamped[k] += moved * head[k] / room
        overflow = sum(bucket_weights.values()) - sum(clamped.values())
    total = sum(clamped.values())
    if total <= 1e-9:
        return {"a1_cash": 1.0}
    return {k: v for k, v in clamped.items() if v > 1e-9}


# 프로덕션 위험자산 proxy (RISK_PROXY = a5 + 성장버킷) — scenario_anchor 테스트 정의와 동일.
# (주의: b1..b8+a5+a4 가 아니라 a5 ∪ GROWTH_KEYS 여야 no-view 복원이 성립한다.)
_MANDATE_RISK_BUCKETS = {"a5_gold_infl"} | set(GROWTH_KEYS)
_FX_CREDIT_SPREAD = 0.02


def _fx_credit_extra_views(buckets, fx_regime, credit_regime, base_spread=_FX_CREDIT_SPREAD):
    """fx/credit 결정론 상대 view → (P,Q,conf). over/under 쌍을 zero-sum row 로."""
    import numpy as np
    rows = []
    if credit_regime == "crisis":
        rows.append(("a3_us_rates", "b9_risk_credit"))
    if fx_regime == "usd_risk_off":
        rows.append(("a4_safe_fx", "b1_kr_equity"))
    n = len(buckets)
    if not rows:
        return np.zeros((0, n)), np.zeros(0), np.zeros(0)
    P = np.zeros((len(rows), n)); Q = np.zeros(len(rows)); conf = np.zeros(len(rows))
    for r, (ov, un) in enumerate(rows):
        if ov in buckets and un in buckets:
            P[r, buckets.index(ov)] = 0.5; P[r, buckets.index(un)] = -0.5
            P[r, :] -= P[r, :].mean()   # zero-sum
            Q[r] = base_spread; conf[r] = 0.9
    return P, Q, conf


def build_bl_bucket_weights(as_of, quadrant, ranking, *, fx_regime="neutral",
                            credit_regime="neutral", delta=2.5, base_spread=0.04,
                            turnover_cap=0.35, window_days=730):
    """BL 버킷 비중 (dict) + attribution meta. Σ fetch(as_of) → bl_allocate. 실패 시 baseline."""
    import pandas as pd
    base = pd.Series(QUADRANT_BASELINE[quadrant])
    try:
        rets = fetch_bucket_proxy_returns(as_of, window_days=window_days)
        Sigma, cov_meta = bucket_covariance(rets, min_obs=252)
        pinned = cov_meta.get("pinned", []) if not Sigma.empty else list(base.index)
    except Exception as e:  # noqa: BLE001
        logger.warning("BL Σ fetch failed (%s) → baseline", e)
        return ({k: float(v) for k, v in base.items()},
                {"__global__": {"status": "baseline_no_sigma", "reason": str(e)[:80]}})
    buckets = list(base.index)
    extra = _fx_credit_extra_views(buckets, fx_regime, credit_regime)
    res = bl_engine.bl_allocate(
        Sigma if not Sigma.empty else None, base, ranking,
        pinned=pinned, delta=delta, base_spread=base_spread, turnover_cap=turnover_cap,
        growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE_RISK_BUCKETS,
        extra_views=extra,
    )
    # PHIL-4: Σ is gone by report time, so persist a COMPACT correlation summary
    # (nested dict, 4dp) into meta so the philosophy report can render the
    # 단일리스크통제 / AI 쏠림 통제 fact (top correlated pair + cluster weight sum).
    # Only when Σ is non-empty; round to keep it serializable/compact.
    if not Sigma.empty:
        try:
            from tradingagents.skills.portfolio.bl_facts import correlation_from_cov
            Corr = correlation_from_cov(Sigma)
            res["meta"].setdefault("__global__", {})["correlation"] = {
                a: {b: round(float(Corr.loc[a, b]), 4) for b in Corr.columns}
                for a in Corr.index
            }
        except Exception as e:  # noqa: BLE001 — correlation summary is auxiliary
            logger.warning("BL correlation summary skipped (%s)", e)
    return ({k: float(v) for k, v in res["weights"].items() if v > 1e-9}, res["meta"])


def _bl_step_a_attribution(baseline, final, realized, bl_meta):
    """BL 경로 attribution: prior→final(의도)→realized + 버킷 status. (philosophy 역추적용)."""
    buckets = {}
    for b in set(baseline) | set(final) | set(realized):
        base_r = round(float(baseline.get(b, 0.0)), 6)
        fin_r = round(float(final.get(b, 0.0)), 6)
        real_r = round(float(realized.get(b, 0.0)), 6)
        if abs(base_r) < 1e-9 and abs(fin_r) < 1e-9 and abs(real_r) < 1e-9:
            continue
        buckets[b] = {
            "baseline": base_r,
            "view_shift": round(fin_r - base_r, 6),       # prior→의도 (BL view 기여)
            "final": fin_r,
            "realized": real_r,
            "intent_vs_realized": round(real_r - fin_r, 6),
            "status": (bl_meta.get(b) or {}).get("status", "bl"),
        }
    return {"method": "bl", "buckets": buckets, "global": bl_meta.get("__global__", {})}


def create_trader_allocator(step_a_llm):
    structured_a = bind_structured(step_a_llm, BucketTilt, "TraderStepA")

    def node(state):
        uni = _load_universe(state["universe_path"])
        pool = _pool_by_bucket(uni)
        aum = {e.ticker: e.aum_krw for e in uni.etfs}
        sub_cat = {e.ticker: e.sub_category for e in uni.etfs}
        idx_of = {e.ticker: e.underlying_index for e in uni.etfs}
        name_of = {e.ticker: e.name for e in uni.etfs}
        capital = float(state.get("capital_krw") or 0.0)
        _dials = state.get("portfolio_dials") or {}

        # technical_report.factor_panel — vol haircut + risk-adj momentum 둘 다 사용.
        # LLM(Step A) 가 이종 버킷 sub_category 후보(모멘텀/AUM 힌트)를 보고 view 를
        # 내도록, 프롬프트 구성 전에 미리 산출한다 (없으면 빈 패널 → no-op).
        tr = state.get("technical_report")
        fp = getattr(tr, "factor_panel", None) or {}
        w_vol = _dials.get("w_vol", 0.4)
        momentum = risk_adjusted_momentum({t: fp.get(t) for t in aum}, w_vol=w_vol)

        # --- Step A: quadrant 앵커 + macro modifiers + LLM tilt + 투영 ---
        quadrant = _resolve_quadrant(state)
        confidence = _resolve_confidence(state)
        rd = state.get("research_decision")
        risk_tilt = (getattr(rd, "risk_tilt", "neutral") if rd else "neutral") or "neutral"
        fx_regime = _resolve_fx_regime(state)
        credit_regime = _resolve_credit_regime(state)

        # B6: opt-in Black-Litterman bucket weights (flag portfolio_dials["use_bl"]).
        # Default False → the entire old project_to_band path runs byte-unchanged.
        # Phase B uses a FIXED ranking (state["bl_fixed_ranking"]); LLM ranking is Phase C.
        # q_baseline/anchor/tilt/bucket_vol are referenced downstream (attribution/step_a),
        # so the BL branch provides inert defaults for them.
        use_bl = bool(_dials.get("use_bl", False))
        bl_meta: dict = {}
        # 이종 버킷 sub_category 후보(모멘텀/AUM 힌트) — BL/비-BL 두 Step A 프롬프트가 공유.
        het_candidates = _heterogeneous_subcat_candidates(pool, sub_cat, aum, momentum)
        if use_bl:
            # Phase C: bl_fixed_ranking(gate-2/test override)가 없으면 LLM 이 상대순위
            # (BucketTilt.bucket_ranking)를 낸다. sub_category_views 도 LLM tilt 에 실려
            # 비-BL 경로와 동일하게 Step B 이종 선정으로 흐른다.
            q_baseline = QUADRANT_BASELINE[quadrant]
            anchor = dict(q_baseline)
            bucket_vol = {}
            as_of_bl = date.fromisoformat(state["as_of_date"])
            if state.get("bl_fixed_ranking") is not None:
                ranking = state["bl_fixed_ranking"]            # gate-2 / tests override
                tilt = BucketTilt()                            # downstream attribution inert
            else:
                tilt = state.get("cached_tilt") or invoke_structured_obj(
                    structured_a,
                    _step_a_prompt_bl(state, quadrant, fx_regime, credit_regime, het_candidates),
                    BucketTilt(), "TraderStepA",
                )
                ranking = _ranking_from_tilt(tilt)
            bucket_weights, bl_meta = build_bl_bucket_weights(
                as_of_bl, quadrant, ranking, fx_regime=fx_regime, credit_regime=credit_regime,
                delta=float(_dials.get("bl_delta", 2.5)),
                base_spread=float(_dials.get("bl_base_spread", 0.04)),
                turnover_cap=float(_dials.get("bl_turnover_cap", 0.50)),
            )
            bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)
            # Step-A '의도'(BL intent) 스냅샷 — Step B/repair/cutoff 가 bucket_weights 를
            # 변형하기 전. BL-native attribution(prior→view_shift→final→realized)에 쓴다.
            bl_intent_buckets = dict(bucket_weights)
        else:
            q_baseline = QUADRANT_BASELINE[quadrant]
            hard_bands = {b: hard_band(quadrant, b, q_baseline[b]) for b in q_baseline}
            hmin = {b: hard_bands[b][0] for b in hard_bands}
            hmax = {b: hard_bands[b][1] for b in hard_bands}
            anchor = apply_macro_modifiers(q_baseline, risk_tilt, credit_regime, fx_regime, hmin, hmax)
            eff = {b: effective_band(anchor[b], hmin[b], hmax[b], confidence)
                   for b in anchor}
            tilt = state.get("cached_tilt") or invoke_structured_obj(
                structured_a,
                _step_a_prompt(state, quadrant, risk_tilt, fx_regime, credit_regime,
                               confidence, anchor, eff, het_candidates),
                BucketTilt(), "TraderStepA",
            )
            eff_lo = {b: eff[b][0] for b in eff}   # eff[b] = (eff_min, eff_max)
            eff_hi = {b: eff[b][1] for b in eff}
            bucket_weights = project_to_band(anchor, tilt.tilts, eff_lo, eff_hi)
            # 변동성 haircut: 고변동 버킷 축소 → 저변동 재배분 (technical_report 없으면 no-op)
            vol_of = {t: getattr(fp.get(t), "realized_vol_60d", None) for t in aum}
            pool_tickers = {b: [e.ticker for e in pool.get(b, [])] for b in bucket_weights}
            bucket_vol = bucket_volatility(pool_tickers, vol_of, aum)
            _hc = {}
            if "vol_haircut_floor" in _dials:
                _hc["floor"] = _dials["vol_haircut_floor"]
            if "vol_haircut_margin" in _dials:
                _hc["margin"] = _dials["vol_haircut_margin"]
            bucket_weights = apply_vol_haircut(bucket_weights, bucket_vol, **_hc)
            bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)

        selections: dict[str, list[str]] = {}
        het_traces: dict[str, dict] = {}
        temperature = _dials.get("softmax_temperature", 1.0)
        for bkey, w in bucket_weights.items():
            if w <= 0:
                continue
            eligible = [e.ticker for e in pool[bkey]]
            is_het = bkey in HETEROGENEOUS_BUCKETS
            _trace: dict | None = {} if is_het else None
            selections[bkey] = select_representative_candidates(
                bucket_key=bkey, eligible=eligible, aum=aum,
                sub_category=sub_cat, underlying_index=idx_of,
                name=name_of, quadrant=quadrant, fx_regime=fx_regime,
                bucket_weight=w, capital_krw=capital,
                sub_category_views=(tilt.sub_category_views.get(bkey) if is_het else None),
                momentum=momentum,
                min_etf_aum_krw=_dials.get("min_etf_aum_krw", 10e9),
                top_k=_dials.get("top_k_heterogeneous", 3),
                trace=_trace,
            )
            if is_het and _trace:
                het_traces[bkey] = _trace

        # 동질 버킷은 AUM 가중, 이종 버킷은 risk-adj 모멘텀 softmax 가중.
        # 버킷별로 partition 해 각각 배분 후 merge — 동질 동작은 정확히 보존.
        def _allocate(bw, sel):
            het_bw = {b: w for b, w in bw.items() if b in HETEROGENEOUS_BUCKETS}
            hom_bw = {b: w for b, w in bw.items() if b not in HETEROGENEOUS_BUCKETS}
            out = aum_weighted_allocation(hom_bw, sel, aum)
            if het_bw:
                for t, wt in momentum_weighted_allocation(
                        het_bw, sel, momentum, temperature=temperature).items():
                    out[t] = out.get(t, 0.0) + wt
            return out

        try:
            weights = _allocate(bucket_weights, selections)
        except InfeasibleBucket as exc:
            logger.warning("within-bucket infeasible (%s) — AUM top-N 으로 강제 보충", exc)
            for bkey, w in bucket_weights.items():
                if w <= 0:
                    continue
                need = max(1, math.ceil(w / SINGLE_CAP - 1e-9))
                selections[bkey] = [
                    e.ticker for e in sorted(pool[bkey], key=lambda e: -e.aum_krw)
                ][:max(need, len(selections.get(bkey, [])))]
            weights = _allocate(bucket_weights, selections)

        s = sum(weights.values())
        if s > 0:
            weights = {t: w / s for t, w in weights.items()}

        # 위험자산 70% + 세부자산(category) + 상관군집(35%) cap deterministic repair
        # (spec §7, 대회 §2.2) — validator 정의(bucket_for_etf / e.category)로 측정해
        # realized 가 모든 cap 이내 보장. category↔risk↔cluster 교대 반복으로 상호작용
        # 수렴(_repair_all_weights). Stage 5 가 하드 검증.
        _meta = {e.ticker: e for e in uni.etfs}
        _cat_of = {e.ticker: e.category for e in uni.etfs}
        # 상관군집 cap(35%, self-imposed) — Stage 1 technical 의 correlation_clusters.
        # 이 노드에 없으면 [] → repair_cluster_cap 은 no-op (안전).
        _clusters = state.get("correlation_clusters") or []
        def _is_risk(t):
            e = _meta.get(t)
            return bool(e) and bucket_for_etf(e) in RISK_BUCKET_NAMES
        def _repair_all(w):
            return _repair_all_weights(w, _cat_of, CATEGORY_CAPS, _is_risk, _clusters)
        weights = _repair_all(weights)

        # 실행상 무의미한 극소액 잔여 정리 (분산 소액 2~5%는 보존) → 재분배가 cap
        # 비율을 흔들 수 있어 repair 를 재적용해 모든 cap 재보장.
        _floor = float(_dials.get("min_holding_weight", NEGLIGIBLE_FLOOR))
        weights = drop_negligible_holdings(weights, _floor)
        weights = _repair_all(weights)

        # 컷오프로 ETF 가 빠지면 bucket 실현 비중도 변하므로, 최종 ETF weights 를
        # 14-bucket 으로 역집계해 bucket_target/attribution(→ philosophy)에 쓴다.
        # step_a 분해는 Step A '의도'라 컷오프 전 bucket_weights 를 그대로 유지한다.
        realized_bucket_weights = aggregate_weights_to_buckets(weights, selections)

        # 대회 공식 위험자산(RISK_BUCKET_NAMES) 합 — validator·repair 와 동일 정의로 리포팅
        risk_pct = sum(w for t, w in weights.items() if _is_risk(t))
        bucket_target = BucketTarget(
            weights=realized_bucket_weights,
            rationale=(f"risk_tilt={risk_tilt} fx={fx_regime} credit={credit_regime}"
                       + f" / risk={risk_pct*100:.1f}%")[:500],
        )
        candidate_set = CandidateSet(
            bucket_to_tickers={k: v for k, v in selections.items() if v},
            selection_criteria="deterministic carrier: core sub_category + AUM + index-dedup",
            total_candidates=sum(len(v) for v in selections.values()) or 1,
        )
        weight_vector = WeightVector(
            method=OptimizationMethod.AUM_WEIGHTED,
            # 9dp (not 6dp): _repair_all_weights drives risk/category/cluster sums
            # to EXACTLY their caps. Rounding ~20 holdings to 6dp accumulates
            # ~N×5e-7 of drift, which can push a realized bucket sum over the
            # Stage-5 validator tolerance (FLOAT_TOLERANCE=1e-6 in
            # concentration_check) by a parts-per-million rounding artifact —
            # causing spurious BL→min-variance fallback. 9dp bounds drift to
            # ~N×5e-10 ≪ 1e-6 while staying well inside WeightVector._normalize's
            # 1e-3 sum tolerance.
            weights={t: round(w, 9) for t, w in weights.items() if w > 1e-6},
            rationale=f"quadrant-anchor tilt + AUM within-bucket. risk={risk_pct*100:.1f}%",
        )
        # Step A 비중 분해(앵커→시나리오→판단→최종) — "왜 이 비중인지" 역추적용.
        # 항등식: baseline + scenario_delta + tilt_applied == final.
        step_a_buckets: dict[str, dict[str, float]] = {}
        for b in GAPS_BUCKET_KEYS:
            base_r = round(q_baseline.get(b, 0.0), 6)
            scen_r = round(anchor.get(b, 0.0) - q_baseline.get(b, 0.0), 6)
            fin_r = round(bucket_weights.get(b, 0.0), 6)
            if fin_r <= 1e-6 and abs(scen_r) <= 1e-9 and not tilt.tilts.get(b):
                continue
            step_a_buckets[b] = {
                "baseline": base_r,
                "scenario_delta": scen_r,
                "tilt_requested": round(tilt.tilts.get(b, 0.0), 6),
                "tilt_applied": round(fin_r - base_r - scen_r, 6),
                "final": fin_r,
            }
        attribution = {
            "bucket_weights": realized_bucket_weights,
            "realized_risk_pct": risk_pct,
            "n_holdings": len(weight_vector.weights),
            "vol_haircut": {"bucket_vol": bucket_vol},
            "step_a": {
                "quadrant": quadrant,
                "risk_tilt": risk_tilt,
                "fx_regime": fx_regime,
                "credit_regime": credit_regime,
                "confidence": confidence,
                "tilt_rationale": tilt.rationale,
                "tilt": dict(tilt.tilts),
                "buckets": step_a_buckets,
                # 이종 버킷 LLM 테마 view + 결정론 선정/폴백 trace — philosophy 역추적용.
                "sub_category_views": {b: dict(v) for b, v in tilt.sub_category_views.items()},
                "heterogeneous_selection": het_traces,
            },
        }
        if use_bl:
            # BL 경로는 tilt/scenario_delta 가 없다 — 버킷 분해를 BL-native
            # (prior baseline → view_shift(의도) → final → realized + 버킷 Σ status)로 교체.
            # LLM sub_category_views / 이종 선정 trace 는 BL 경로에서도 Step B 를
            # 구동하므로 philosophy 역추적용으로 보존한다.
            bl_step_a = _bl_step_a_attribution(
                QUADRANT_BASELINE[quadrant], bl_intent_buckets,
                realized_bucket_weights, bl_meta,
            )
            bl_step_a["sub_category_views"] = {
                b: dict(v) for b, v in tilt.sub_category_views.items()
            }
            bl_step_a["heterogeneous_selection"] = het_traces
            attribution["step_a"] = bl_step_a
            attribution["bl"] = bl_meta   # BL branch attribution (Σ status, per-bucket BL/pinned)
        return {
            "bucket_target": bucket_target,
            "candidate_set": candidate_set,
            "weight_vector": weight_vector,
            "method_choice": {"method": "aum_weighted"},
            "allocation_attribution": attribution,
            # B1 fix: count each allocator run so validation_router can route to
            # fallback after MAX_ALLOCATION_ATTEMPTS. Without this the retry→fallback
            # cycle never terminates (attempts stuck at 0) and a persistently
            # failing validation aborts the run with GraphRecursionError.
            "allocation_attempts": state.get("allocation_attempts", 0) + 1,
        }

    return node
