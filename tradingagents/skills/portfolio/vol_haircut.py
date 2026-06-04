"""Step A 변동성 haircut — 고변동 버킷 축소 → 저변동 재배분 (spec 2026-06-04).

리스크 일관성 오버레이(방향 베팅 아님). realized_vol_60d 기반, 결정론·순수.
technical_report(factor_panel) 부재 시 호출부가 빈 bucket_vol 전달 → no-op.
"""
from __future__ import annotations

_VOL_HAIRCUT_FLOOR: float = 0.6      # 최대 40% haircut
_VOL_HAIRCUT_MARGIN: float = 0.2     # ref 대비 20% 초과 시에만 haircut
_MIN_VOL_REDISTRIB: float = 0.03     # 재배분 가중 vol floor (cash 과집중 방지)


def bucket_volatility(
    pool: dict[str, list[str]],
    vol_of: dict[str, float | None],
    aum: dict[str, float],
) -> dict[str, float]:
    """버킷별 vol = 풀 ETF realized_vol_60d 의 AUM-가중 평균. None/0 skip.

    유효 vol 종목 0개 버킷은 결과에서 생략(haircut 대상 아님).
    """
    out: dict[str, float] = {}
    for b, tickers in pool.items():
        num = den = 0.0
        for t in tickers:
            v = vol_of.get(t)
            if v is None or v <= 0:
                continue
            a = max(aum.get(t, 0.0), 0.0)
            num += a * v
            den += a
        if den > 0:
            out[b] = num / den
    return out


def apply_vol_haircut(
    bucket_weights: dict[str, float],
    bucket_vol: dict[str, float],
    floor: float = _VOL_HAIRCUT_FLOOR,
    margin: float = _VOL_HAIRCUT_MARGIN,
) -> dict[str, float]:
    """한쪽 역변동성 haircut + 저변동 재배분. 합 보존.

    ref = bucket_weights 가중 평균 vol(포트폴리오 평균 vol). vol>ref·(1+margin) 버킷만
    factor=max(floor, thr/vol) 축소(thr=ref·(1+margin), 임계 연속). freed → 저변동(vol<ref)
    버킷에 (현재비중 / max(vol, MIN)) 비례 배분. vol 데이터 없으면 무변경.
    """
    present = {b: bucket_vol[b] for b in bucket_weights if b in bucket_vol}
    wsum = sum(bucket_weights[b] for b in present)
    if not present or wsum <= 0:
        return dict(bucket_weights)

    ref = sum(bucket_weights[b] * present[b] for b in present) / wsum
    thr = ref * (1.0 + margin)

    out = dict(bucket_weights)
    freed = 0.0
    for b in present:
        if present[b] > thr:
            factor = max(floor, thr / present[b])
            new = out[b] * factor
            freed += out[b] - new
            out[b] = new
    if freed <= 1e-12:
        return out

    recips = {b: out[b] / max(present[b], _MIN_VOL_REDISTRIB)
              for b in present if present[b] < ref and out[b] > 0}
    base = sum(recips.values())
    if base <= 1e-12:
        recips = {b: out[b] for b in present if present[b] <= thr and out[b] > 0}
        base = sum(recips.values())
    if base <= 1e-12:
        return out
    for b, wgt in recips.items():
        out[b] += freed * wgt / base
    return out
