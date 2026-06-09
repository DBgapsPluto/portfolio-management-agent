"""세부자산(category)별 cap deterministic repair (대회 §2.2).

risk_repair 패턴: category 합 > cap 이면 그 category 종목을 비례 축소,
freed 를 headroom(단일캡 ∩ category캡) 있는 종목에 water-fill. 순수·결정론.

단일캡(20%)·위험자산캡(70%)과 직교하는 제약이므로 repair_risk_cap 과 교대 적용한다
(trader_allocator / daily_full 의 통합부 참조).
"""
from __future__ import annotations

from tradingagents.skills.mandate.concentration_check import FLOAT_TOLERANCE
from tradingagents.skills.portfolio.within_bucket import SINGLE_CAP

_MAX_ITERS: int = 50
_CASH = "CASH"


def repair_category_caps(
    weights: dict[str, float],
    ticker_to_category: dict[str, str | None],
    category_caps: dict[str, float],
) -> dict[str, float]:
    """category 합 ≤ cap 보장(best-effort). 모든 category 이내면 무변경.

    headroom = min(SINGLE_CAP − w, category_cap − category_sum) → 단일·category 동시 보장.
    CASH/미분류는 category 제약 없음(단일캡만). water-fill 시 headroom 을 실시간 재계산해
    같은 category 종목들의 분배 합이 cap 을 넘지 않게 한다. 분배처 부족(degenerate
    infeasible)이면 best-effort renormalize 반환 — 최종 hard 판정은 validator.
    """
    if not weights:
        return {}

    def cat_of(t: str):
        return None if t == _CASH else ticker_to_category.get(t)

    def cat_sum(out: dict, c: str) -> float:
        return sum(w for t, w in out.items() if cat_of(t) == c)

    def headroom(out: dict, t: str) -> float:
        single_room = SINGLE_CAP - out[t]
        c = cat_of(t)
        if c is None:
            return max(0.0, single_room)
        cat_room = category_caps.get(c, SINGLE_CAP) - cat_sum(out, c)
        return max(0.0, min(single_room, cat_room))

    out = dict(weights)
    for _ in range(_MAX_ITERS):
        over = {c: cap for c, cap in category_caps.items()
                if cat_sum(out, c) > cap + FLOAT_TOLERANCE}
        if not over:
            break
        # 1) 초과 category 비례 축소 (상대비 보존)
        freed = 0.0
        for c, cap in over.items():
            cs = cat_sum(out, c)
            scale = cap / cs
            for t in out:
                if cat_of(t) == c:
                    freed += out[t] * (1.0 - scale)
                    out[t] *= scale
        # 2) freed 를 headroom 있는 종목에 현재비중 비례 water-fill (headroom 실시간 재계산)
        for _ in range(_MAX_ITERS):
            if freed <= 1e-12:
                break
            elig = [t for t in out if headroom(out, t) > 1e-12]
            room = sum(headroom(out, t) for t in elig)
            if room <= 1e-12:
                break  # 분배처 없음 → best-effort
            give = min(freed, room)
            base = sum(out[t] for t in elig) or 1.0
            actual = 0.0
            for t in elig:
                add_t = min(give * (out[t] / base), headroom(out, t))
                out[t] += add_t
                actual += add_t
            if actual <= 1e-15:
                break
            freed -= actual

    s = sum(out.values())
    return {t: w / s for t, w in out.items()} if s > 0 else dict(weights)
