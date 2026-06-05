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


# cap 하 합=1 이 가능한 최소 종목 수 (ceil(1/0.20)=5). 이보다 적으면 컷오프 보류.
_MIN_FEASIBLE_HOLDINGS: int = math.ceil(1.0 / SINGLE_CAP - _EPS)


def _redistribute_single_cap(weights: dict[str, float]) -> dict[str, float]:
    """20% 단일 cap water-filling — 초과분을 미달 종목에 비례 재분배."""
    w = dict(weights)
    for _ in range(50):
        over = [t for t, x in w.items() if x > SINGLE_CAP + _EPS]
        if not over:
            break
        excess = sum(w[t] - SINGLE_CAP for t in over)
        for t in over:
            w[t] = SINGLE_CAP
        under = {t: x for t, x in w.items() if x < SINGLE_CAP - _EPS}
        tot = sum(under.values())
        if tot <= _EPS:
            break
        for t in under:
            w[t] += excess * under[t] / tot
    return w


def aggregate_weights_to_buckets(
    weights: dict[str, float], selections: dict[str, list[str]],
) -> dict[str, float]:
    """최종 ETF weights 를 14-bucket 비중으로 역집계 (selections=bucket→tickers).

    컷오프(drop_negligible_holdings)로 weights 에서 빠진 종목의 bucket 은 자동으로
    제외되므로, bucket_target/attribution(→ philosophy)이 실현 비중을 정확히 반영한다.
    """
    ticker_to_bucket = {t: b for b, ts in selections.items() for t in ts}
    out: dict[str, float] = {}
    for t, w in weights.items():
        b = ticker_to_bucket.get(t)
        if b is not None:
            out[b] = out.get(b, 0.0) + w
    return out


def drop_negligible_holdings(
    weights: dict[str, float], floor: float,
) -> dict[str, float]:
    """실행상 무의미한 극소액 잔여를 제거하고 비례 재분배 + 20% cap 재적용.

    '비율 컷오프'가 아니다 — floor 를 작게(예: 0.01) 두어 분산 목적의 소액
    포지션(2~5%)은 보존하고, 성과 기여가 거래비용보다도 작은 잔여(예: 0.25%)만
    정리한다. floor≤0 이면 no-op. 제거 후 종목이 _MIN_FEASIBLE_HOLDINGS(5) 미만이면
    20% cap 하 합=1 이 불가능하고 분산도 과도하게 훼손되므로 원본을 유지한다(방어).
    """
    if floor <= 0:
        return dict(weights)
    kept = {t: w for t, w in weights.items() if w >= floor}
    if len(kept) < _MIN_FEASIBLE_HOLDINGS:
        return dict(weights)
    s = sum(kept.values())
    if s <= _EPS:
        return dict(weights)
    redistributed = {t: w / s for t, w in kept.items()}
    return _redistribute_single_cap(redistributed)
