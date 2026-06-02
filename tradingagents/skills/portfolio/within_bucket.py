"""버킷 비중을 선정 종목에 AUM 가중 배분 + 단일 20% cap water-filling.

위험자산(≤70%) 검사는 여기서 하지 않는다 — realized_risk_weight() 별도 함수가
최종 weight + per-ETF 위험/안전 으로 계산. (Stage 5 가 하드 검증.)
"""
from __future__ import annotations

import math

SINGLE_CAP: float = 0.20
_EPS: float = 1e-9


class InfeasibleBucket(Exception):
    """버킷 비중을 단일 20% cap 안에서 배분 불가 (종목 부족)."""


def _allocate_one_bucket(weight: float, tickers: list[str],
                         aum: dict[str, float]) -> dict[str, float]:
    if weight <= _EPS:
        return {}
    if not tickers:
        raise InfeasibleBucket(f"bucket weight {weight} 인데 종목 0개")
    need = math.ceil(weight / SINGLE_CAP - _EPS)
    if len(tickers) < need:
        raise InfeasibleBucket(
            f"weight {weight} 에 최소 {need}종목 필요, {len(tickers)}개뿐")

    remaining = set(tickers)
    out: dict[str, float] = {}
    budget = weight
    while remaining:
        total_aum = sum(max(aum.get(t, 0.0), 0.0) for t in remaining)
        if total_aum <= _EPS:
            share = budget / len(remaining)
            raw = {t: share for t in remaining}
        else:
            raw = {t: budget * max(aum.get(t, 0.0), 0.0) / total_aum
                   for t in remaining}
        newly_capped = {t for t, w in raw.items() if w > SINGLE_CAP + _EPS}
        if not newly_capped:
            out.update(raw)
            break
        for t in newly_capped:
            out[t] = SINGLE_CAP
            budget -= SINGLE_CAP
            remaining.discard(t)
        if not remaining and budget > _EPS:
            raise InfeasibleBucket(f"잔여 예산 {budget} 배분 불가 (전부 capped)")
    return out


def aum_weighted_allocation(
    bucket_weights: dict[str, float],
    selections: dict[str, list[str]],
    aum: dict[str, float],
) -> dict[str, float]:
    """14-bucket 비중 + 버킷별 선정 종목 + ticker→AUM → ticker→최종 weight."""
    final: dict[str, float] = {}
    for bkey, w in bucket_weights.items():
        part = _allocate_one_bucket(w, selections.get(bkey, []), aum)
        for t, wt in part.items():
            final[t] = final.get(t, 0.0) + wt
    return final


def realized_risk_weight(
    weights: dict[str, float],
    risk_flag: dict[str, str],
) -> float:
    """최종 weight 중 universe.json bucket=='위험' 인 종목 비중 합 (mandate ≤0.70)."""
    return sum(w for t, w in weights.items() if risk_flag.get(t) == "위험")
