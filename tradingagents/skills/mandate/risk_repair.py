"""위험자산 70% cap deterministic repair (E2E 발견 — Step B spec §7).

trader 노드가 ETF weight 확정 후 호출. realized 위험자산 > cap 이면 위험 포지션을 비례 축소,
freed 를 안전 포지션에 water-fill(단일 20% 한도). 위험 분류 predicate 는 호출부가 주입
(node 는 validator 와 동일한 bucket_for_etf ∈ RISK_BUCKET_NAMES 로 구성) → validator 통과 보장.
순수·결정론.
"""
from __future__ import annotations

from typing import Callable

from tradingagents.skills.mandate.concentration_check import (
    HARD_RISK_ASSET_CAP, FLOAT_TOLERANCE,
)
from tradingagents.skills.portfolio.within_bucket import SINGLE_CAP

_MAX_ITERS: int = 50


def repair_risk_cap(
    weights: dict[str, float],
    is_risk: Callable[[str], bool],
    cap: float = HARD_RISK_ASSET_CAP,
) -> dict[str, float]:
    """위험자산 합 ≤ cap 보장. cap 이하면 무변경."""
    if not weights:
        return {}
    risk_sum = sum(w for t, w in weights.items() if is_risk(t))
    if risk_sum <= cap + FLOAT_TOLERANCE:
        return dict(weights)

    out = dict(weights)
    scale = cap / risk_sum
    for t in out:
        if is_risk(t):
            out[t] *= scale

    safe = [t for t in out if not is_risk(t)]
    add = (1.0 - cap) - sum(out[t] for t in safe)   # = risk_sum - cap (freed)
    for _ in range(_MAX_ITERS):
        if add <= 1e-12:
            break
        eligible = {t: out[t] for t in safe if out[t] < SINGLE_CAP - 1e-12}
        base = sum(eligible.values())
        if base <= 1e-12:
            break
        # Distribute proportional to current weight (preserves relative proportions),
        # but clamp at SINGLE_CAP. Remainder loops back until exhausted.
        give = min(add, sum(SINGLE_CAP - v for v in eligible.values()))
        for t, v in eligible.items():
            delta = give * v / base
            room = SINGLE_CAP - out[t]
            out[t] += min(delta, room)
        add -= give

    s = sum(out.values())
    return {t: w / s for t, w in out.items()} if s > 0 else dict(weights)
