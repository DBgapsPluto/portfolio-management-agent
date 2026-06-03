"""Stage 3 trader/allocator — LLM 2-step 배분 + 결정적 AUM 종목내 배분.

step A: quadrant 앵커 baseline 대비 버킷별 tilt 결정 (BucketTilt) → 밴드 투영
step B: 비중>0 버킷의 종목 선정 (StockSelection)
종목내 비중: AUM 가중 + 단일 20% cap (within_bucket.aum_weighted_allocation)

위험자산(≤70%)은 최종 weight 에 per-ETF 위험/안전 적용해 검사 — Stage 5 가 하드 검증.
"""
from __future__ import annotations
import json
import logging
import math
from pathlib import Path

from tradingagents.dataflows.universe import Universe
from tradingagents.agents.utils.structured import bind_structured, invoke_structured_obj
from tradingagents.schemas.portfolio import (
    StockSelection, BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod, BucketTilt,
)
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, BUCKET_KR_NAME,
)
from tradingagents.skills.portfolio.within_bucket import (
    aum_weighted_allocation, realized_risk_weight, InfeasibleBucket, SINGLE_CAP,
)
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band, effective_band, project_to_band,
)

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
_STEP_B_SYSTEM = (
    "당신은 트레이더다. 정해진 버킷 비중에 맞춰, 각 버킷에서 실제 매수할 ETF를 "
    "고른다. AUM·유동성이 충분하고 버킷 성격에 맞는 대표 종목을 고르되, 한 버킷의 "
    "비중이 클수록 단일 종목 20% 상한 때문에 더 많은 종목이 필요하다(최소 "
    "ceil(버킷비중/0.20)개)."
)


def _step_a_prompt(state, quadrant, confidence, conviction, anchor, eff) -> list[dict]:
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
        f"## Regime: {quadrant} (confidence {confidence:.2f}), conviction {conviction}\n\n"
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


def _step_b_prompt(state, bucket_weights, pool) -> list[dict]:
    lines = []
    for k, w in bucket_weights.items():
        if w <= 0:
            continue
        min_n = max(1, math.ceil(w / SINGLE_CAP - 1e-9))
        cand = sorted(pool.get(k, []), key=lambda e: -e.aum_krw)
        listing = "\n".join(
            f"    {e.ticker} {e.name} (AUM {e.aum_krw:,.0f}, {e.bucket})"
            for e in cand
        )
        lines.append(
            f"### {k} ({BUCKET_KR_NAME[k]}) 비중 {w*100:.1f}% — 최소 {min_n}종목\n{listing}"
        )
    return [
        {"role": "system", "content": _STEP_B_SYSTEM},
        {"role": "user", "content": (
            "## 버킷별 종목 풀 (비중>0 버킷만)\n" + "\n\n".join(lines) +
            "\n\n각 버킷 key 에 선정 ticker 리스트를 배정하라."
        )},
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


def create_trader_allocator(step_a_llm, step_b_llm):
    structured_a = bind_structured(step_a_llm, BucketTilt, "TraderStepA")
    structured_b = bind_structured(step_b_llm, StockSelection, "TraderStepB")

    def node(state):
        uni = _load_universe(state["universe_path"])
        pool = _pool_by_bucket(uni)
        aum = {e.ticker: e.aum_krw for e in uni.etfs}
        risk_flag = {e.ticker: e.bucket for e in uni.etfs}
        valid_tickers = set(aum)

        # --- Step A: quadrant 앵커 + LLM tilt + 투영 ---
        quadrant = _resolve_quadrant(state)
        confidence = _resolve_confidence(state)
        rd = state.get("research_decision")
        conviction = (getattr(rd, "conviction", "medium") if rd else "medium") or "medium"
        anchor = QUADRANT_BASELINE[quadrant]
        hard_bands = {b: hard_band(quadrant, b, anchor[b]) for b in anchor}
        eff = {b: effective_band(anchor[b], hard_bands[b][0], hard_bands[b][1], confidence, conviction)
               for b in anchor}
        tilt = invoke_structured_obj(
            structured_a, _step_a_prompt(state, quadrant, confidence, conviction, anchor, eff),
            BucketTilt(), "TraderStepA",
        )
        eff_lo = {b: eff[b][0] for b in eff}   # eff[b] = (eff_min, eff_max)
        eff_hi = {b: eff[b][1] for b in eff}
        bucket_weights = project_to_band(anchor, tilt.tilts, eff_lo, eff_hi)
        bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)

        ss = invoke_structured_obj(
            structured_b, _step_b_prompt(state, bucket_weights, pool),
            StockSelection(selections={}), "TraderStepB",
        )
        selections: dict[str, list[str]] = {}
        for bkey, w in bucket_weights.items():
            if w <= 0:
                continue
            bucket_tickers = {e.ticker for e in pool[bkey]}
            picked = [t for t in ss.selections.get(bkey, [])
                      if t in valid_tickers and t in bucket_tickers]
            need = max(1, math.ceil(w / SINGLE_CAP - 1e-9))
            if len(picked) < need:
                extra = [e.ticker for e in sorted(pool[bkey], key=lambda e: -e.aum_krw)
                         if e.ticker not in picked]
                picked = (picked + extra)[:max(need, len(picked))]
            selections[bkey] = picked

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

        risk_pct = realized_risk_weight(weights, risk_flag)
        bucket_target = BucketTarget(
            weights=bucket_weights,
            rationale=(getattr(state.get("research_decision"), "dominant_scenario", "")
                       + f" / risk={risk_pct*100:.1f}%")[:500],
        )
        candidate_set = CandidateSet(
            bucket_to_tickers={k: v for k, v in selections.items() if v},
            selection_criteria="LLM trader step B + AUM top-N 보충",
            total_candidates=sum(len(v) for v in selections.values()) or 1,
        )
        weight_vector = WeightVector(
            method=OptimizationMethod.AUM_WEIGHTED,
            weights={t: round(w, 6) for t, w in weights.items() if w > 1e-6},
            rationale=f"quadrant-anchor tilt + AUM within-bucket. risk={risk_pct*100:.1f}%",
        )
        attribution = {
            "bucket_weights": bucket_weights,
            "realized_risk_pct": risk_pct,
            "n_holdings": len(weight_vector.weights),
        }
        return {
            "bucket_target": bucket_target,
            "candidate_set": candidate_set,
            "weight_vector": weight_vector,
            "method_choice": {"method": "aum_weighted"},
            "allocation_attribution": attribution,
        }

    return node
