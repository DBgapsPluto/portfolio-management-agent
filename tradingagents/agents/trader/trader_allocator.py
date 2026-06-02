"""Stage 3 trader/allocator — LLM 2-step 배분 + 결정적 AUM 종목내 배분.

step A: 14-bucket 비중 결정 (BucketAllocation)
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
    BucketAllocation, StockSelection, BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod,
)
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, BUCKET_KR_NAME, BUCKET_CAMP,
)
from tradingagents.skills.portfolio.within_bucket import (
    aum_weighted_allocation, realized_risk_weight, InfeasibleBucket, SINGLE_CAP,
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


_STEP_A_SYSTEM = (
    "당신은 자산배분 트레이더다. 리서치 매니저의 종합 판단을 받아 14개 버킷에 "
    "비중(합=1.0)을 배정한다. 위험자산(주식·원자재·금 등 성장+일부 방어)은 합쳐 "
    "70%를 넘기지 말 것(대회 룰). 방어 버킷(A1~A5)과 성장 버킷(B1~B9)의 균형을 "
    "매니저 conviction 에 맞춰라."
)
_STEP_B_SYSTEM = (
    "당신은 트레이더다. 정해진 버킷 비중에 맞춰, 각 버킷에서 실제 매수할 ETF를 "
    "고른다. AUM·유동성이 충분하고 버킷 성격에 맞는 대표 종목을 고르되, 한 버킷의 "
    "비중이 클수록 단일 종목 20% 상한 때문에 더 많은 종목이 필요하다(최소 "
    "ceil(버킷비중/0.20)개)."
)


def _bucket_menu() -> str:
    return "\n".join(
        f"  {k} ({BUCKET_KR_NAME[k]}, {BUCKET_CAMP[k]})" for k in GAPS_BUCKET_KEYS
    )


def _step_a_prompt(state) -> list[dict]:
    rd = state.get("research_decision")
    thesis = getattr(rd, "thesis_md", "") if rd else ""
    conviction = getattr(rd, "conviction", "medium") if rd else "medium"
    fb = state.get("allocation_feedback") or []
    fb_txt = "\n".join(f"  - {getattr(v, 'message', str(v))}" for v in fb)
    return [
        {"role": "system", "content": _STEP_A_SYSTEM},
        {"role": "user", "content": (
            f"## 리서치 종합 (conviction={conviction})\n{thesis}\n\n"
            f"## 14 버킷\n{_bucket_menu()}\n\n"
            + (f"## 직전 시도 위반 피드백 (반영 필수)\n{fb_txt}\n\n" if fb_txt else "")
            + "각 버킷 key 에 0~1 비중을 배정(합 1.0). 위험자산 ≤70% 준수."
        )},
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


def _normalize_bucket_weights(raw: dict[str, float]) -> dict[str, float]:
    clean = {k: max(0.0, float(v)) for k, v in raw.items()
             if k in GAPS_BUCKET_KEYS}
    total = sum(clean.values())
    if total <= 1e-9:
        return {"a1_cash": 1.0}
    return {k: v / total for k, v in clean.items() if v > 0}


def _clamp_to_pool_capacity(
    bucket_weights: dict[str, float], pool: dict[str, list]
) -> dict[str, float]:
    """각 버킷을 n_pool * SINGLE_CAP 용량으로 clamp, 초과분은 a1_cash 로 이동 후 재정규화."""
    clamped: dict[str, float] = {}
    overflow = 0.0
    for k, w in bucket_weights.items():
        cap = len(pool.get(k, [])) * SINGLE_CAP
        if w > cap:
            overflow += w - cap
            clamped[k] = cap
        else:
            clamped[k] = w
    if overflow > 1e-9:
        clamped["a1_cash"] = clamped.get("a1_cash", 0.0) + overflow
    total = sum(clamped.values())
    if total <= 1e-9:
        return {"a1_cash": 1.0}
    return {k: v / total for k, v in clamped.items() if v > 1e-9}


def create_trader_allocator(step_a_llm, step_b_llm):
    structured_a = bind_structured(step_a_llm, BucketAllocation, "TraderStepA")
    structured_b = bind_structured(step_b_llm, StockSelection, "TraderStepB")

    def node(state):
        uni = _load_universe(state["universe_path"])
        pool = _pool_by_bucket(uni)
        aum = {e.ticker: e.aum_krw for e in uni.etfs}
        risk_flag = {e.ticker: e.bucket for e in uni.etfs}
        valid_tickers = set(aum)

        ba = invoke_structured_obj(
            structured_a, _step_a_prompt(state),
            BucketAllocation(weights={"a1_cash": 1.0}), "TraderStepA",
        )
        bucket_weights = _normalize_bucket_weights(ba.weights)
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
            rationale=f"14-bucket trader + AUM within-bucket. risk={risk_pct*100:.1f}%",
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
