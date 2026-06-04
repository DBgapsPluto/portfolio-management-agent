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
from pathlib import Path

from tradingagents.dataflows.universe import Universe
from tradingagents.agents.utils.structured import bind_structured, invoke_structured_obj
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod, BucketTilt,
)
from tradingagents.skills.portfolio.candidate_selector import select_representative_candidates
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, BUCKET_KR_NAME,
)
from tradingagents.skills.portfolio.within_bucket import (
    aum_weighted_allocation, InfeasibleBucket, SINGLE_CAP,
)
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band, effective_band, project_to_band,
    SCENARIO_MODIFIER, apply_scenario_modifier,
)
from tradingagents.skills.portfolio.vol_haircut import (
    bucket_volatility, apply_vol_haircut,
)
from tradingagents.skills.mandate.risk_repair import repair_risk_cap
from tradingagents.skills.mandate.concentration_check import RISK_BUCKET_NAMES
from tradingagents.skills.portfolio.sub_category import bucket_for_etf

logger = logging.getLogger(__name__)


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


_STEP_A_SYSTEM = (
    "당신은 자산배분 트레이더다. 주어진 'regime 앵커(baseline)'에서 출발해, "
    "리서치 판단으로 버킷별 tilt(앵커 대비 가감)만 결정한다. 다음 순서로 사고하라:\n"
    "① 리스크 예산: conviction·regime 으로 위험자산 총량 방향(앵커가 이미 ≤70% 지향).\n"
    "② 방어(A1~A5): regime 따라 cash/듀레이션/금·인플레 가감.\n"
    "③ 성장(B1~B9): thesis·key_risks 로 버킷 tilt.\n"
    "④ 자가검증: tilt 는 허용밴드 내, 오버웨이트는 언더웨이트로 펀딩(net≈0).\n"
    "벗어나지 않을 버킷은 tilt 를 생략(=0)하라."
)


def _step_a_prompt(state, quadrant, scenario, confidence, conviction, anchor, eff) -> list[dict]:
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
    body = (
        f"## Regime: {quadrant} / Scenario: {scenario} "
        f"(confidence {confidence:.2f}), conviction {conviction}\n\n"
        f"## 앵커 baseline + 허용밴드 (이 안에서만 tilt)\n{anchor_lines}\n\n"
        f"## 리서치 종합\n{thesis}\n\n"
        f"## 핵심 리스크\n" + ("\n".join(f"  - {r}" for r in key_risks) or "  (없음)") + "\n\n"
        f"## Stage1 요약\n"
        f"매크로: {state.get('macro_summary','(없음)')}\n"
        f"리스크: {state.get('risk_summary','(없음)')}\n"
        f"기술적: {state.get('technical_summary','(없음)')}\n"
        f"뉴스: {state.get('news_summary','(없음)')}\n\n"
        + (f"## 직전 위반 피드백 (반영 필수)\n{fb_txt}\n\n" if fb_txt else "")
        + "각 버킷의 tilt(앵커 대비 가감)를 출력하라. 0 인 버킷은 생략."
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

        # --- Step A: quadrant 앵커 + scenario modifier + LLM tilt + 투영 ---
        quadrant = _resolve_quadrant(state)
        confidence = _resolve_confidence(state)
        rd = state.get("research_decision")
        conviction = (getattr(rd, "conviction", "medium") if rd else "medium") or "medium"
        scenario = (getattr(rd, "dominant_scenario", "neutral") if rd else "neutral") or "neutral"

        q_baseline = QUADRANT_BASELINE[quadrant]
        hard_bands = {b: hard_band(quadrant, b, q_baseline[b]) for b in q_baseline}
        hmin = {b: hard_bands[b][0] for b in hard_bands}
        hmax = {b: hard_bands[b][1] for b in hard_bands}
        # anchor: scenario modifier 로 옮겨진 center (eff_band·LLM tilt 의 기준점)
        anchor = apply_scenario_modifier(q_baseline, scenario, hmin, hmax)
        eff = {b: effective_band(anchor[b], hmin[b], hmax[b], confidence, conviction)
               for b in anchor}
        tilt = state.get("cached_tilt") or invoke_structured_obj(
            structured_a,
            _step_a_prompt(state, quadrant, scenario, confidence, conviction, anchor, eff),
            BucketTilt(), "TraderStepA",
        )
        eff_lo = {b: eff[b][0] for b in eff}   # eff[b] = (eff_min, eff_max)
        eff_hi = {b: eff[b][1] for b in eff}
        bucket_weights = project_to_band(anchor, tilt.tilts, eff_lo, eff_hi)
        # 변동성 haircut: 고변동 버킷 축소 → 저변동 재배분 (technical_report 없으면 no-op)
        tr = state.get("technical_report")
        fp = getattr(tr, "factor_panel", None) or {}
        vol_of = {t: getattr(fp.get(t), "realized_vol_60d", None) for t in aum}
        pool_tickers = {b: [e.ticker for e in pool.get(b, [])] for b in bucket_weights}
        bucket_vol = bucket_volatility(pool_tickers, vol_of, aum)
        _dials = state.get("portfolio_dials") or {}
        _hc = {}
        if "vol_haircut_floor" in _dials:
            _hc["floor"] = _dials["vol_haircut_floor"]
        if "vol_haircut_margin" in _dials:
            _hc["margin"] = _dials["vol_haircut_margin"]
        bucket_weights = apply_vol_haircut(bucket_weights, bucket_vol, **_hc)
        bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)

        selections: dict[str, list[str]] = {}
        for bkey, w in bucket_weights.items():
            if w <= 0:
                continue
            eligible = [e.ticker for e in pool[bkey]]
            selections[bkey] = select_representative_candidates(
                bucket_key=bkey, eligible=eligible, aum=aum,
                sub_category=sub_cat, underlying_index=idx_of,
                name=name_of, quadrant=quadrant, dominant_scenario=scenario,
                bucket_weight=w, capital_krw=capital,
            )

        try:
            weights = aum_weighted_allocation(bucket_weights, selections, aum)
        except InfeasibleBucket as exc:
            logger.warning("within-bucket infeasible (%s) — AUM top-N 으로 강제 보충", exc)
            for bkey, w in bucket_weights.items():
                if w <= 0:
                    continue
                need = max(1, math.ceil(w / SINGLE_CAP - 1e-9))
                selections[bkey] = [
                    e.ticker for e in sorted(pool[bkey], key=lambda e: -e.aum_krw)
                ][:max(need, len(selections.get(bkey, [])))]
            weights = aum_weighted_allocation(bucket_weights, selections, aum)

        s = sum(weights.values())
        if s > 0:
            weights = {t: w / s for t, w in weights.items()}

        # 위험자산 70% cap deterministic repair (spec §7) — validator 정의(bucket_for_etf)로 측정해
        # realized 위험 ≤70% 보장 → 결정론 retry 무한루프/크래시 방지.
        _meta = {e.ticker: e for e in uni.etfs}
        def _is_risk(t):
            e = _meta.get(t)
            return bool(e) and bucket_for_etf(e) in RISK_BUCKET_NAMES
        weights = repair_risk_cap(weights, _is_risk)
        s = sum(weights.values())
        if s > 0:
            weights = {t: w / s for t, w in weights.items()}

        # 대회 공식 위험자산(RISK_BUCKET_NAMES) 합 — validator·repair 와 동일 정의로 리포팅
        risk_pct = sum(w for t, w in weights.items() if _is_risk(t))
        bucket_target = BucketTarget(
            weights=bucket_weights,
            rationale=(getattr(state.get("research_decision"), "dominant_scenario", "")
                       + f" / risk={risk_pct*100:.1f}%")[:500],
        )
        candidate_set = CandidateSet(
            bucket_to_tickers={k: v for k, v in selections.items() if v},
            selection_criteria="deterministic carrier: core sub_category + AUM + index-dedup",
            total_candidates=sum(len(v) for v in selections.values()) or 1,
        )
        weight_vector = WeightVector(
            method=OptimizationMethod.AUM_WEIGHTED,
            weights={t: round(w, 6) for t, w in weights.items() if w > 1e-6},
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
            "bucket_weights": bucket_weights,
            "realized_risk_pct": risk_pct,
            "n_holdings": len(weight_vector.weights),
            "vol_haircut": {"bucket_vol": bucket_vol},
            "step_a": {
                "quadrant": quadrant,
                "scenario": scenario,
                "confidence": confidence,
                "conviction": conviction,
                "tilt_rationale": tilt.rationale,
                "tilt": dict(tilt.tilts),
                "buckets": step_a_buckets,
            },
        }
        return {
            "bucket_target": bucket_target,
            "candidate_set": candidate_set,
            "weight_vector": weight_vector,
            "method_choice": {"method": "aum_weighted"},
            "allocation_attribution": attribution,
        }

    return node
