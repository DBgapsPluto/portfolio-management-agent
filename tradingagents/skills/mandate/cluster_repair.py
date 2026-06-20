"""상관군집 cap deterministic repair (군집합 ≤ cap). self-imposed 35% (대회 규칙 아님).

trader 노드가 ETF weight 확정 후 호출. 초과 군집 멤버를 비례 축소, freed 를
비-군집(어느 군집에도 없는) 포지션에 water-fill(단일 20% 한도) 후 renormalize.
순수·결정론. correlation_check(validator) 와 동일 임계.
"""
from __future__ import annotations

from tradingagents.schemas.technical import Cluster
from tradingagents.skills.portfolio.within_bucket import SINGLE_CAP

CLUSTER_CAP: float = 0.35     # self-imposed (DB GAPS 규칙엔 cluster cap 없음; A2 완화)
FLOAT_TOLERANCE: float = 1e-6
_MAX_ITERS: int = 50


def repair_cluster_cap(
    weights: dict[str, float], clusters: list[Cluster], cap: float = CLUSTER_CAP,
) -> dict[str, float]:
    if not weights or not clusters:
        return dict(weights)
    out = dict(weights)
    all_cluster_members = {t for c in clusters for t in c.members}
    for cluster in clusters:
        members = [t for t in cluster.members if t in out]
        csum = sum(out[t] for t in members)
        if csum <= cap + FLOAT_TOLERANCE:
            continue
        scale = cap / csum
        for t in members:
            out[t] *= scale
        freed = csum - cap
        recipients = [t for t in out if t not in all_cluster_members]
        for _ in range(_MAX_ITERS):
            if freed <= 1e-12:
                break
            eligible = {t: out[t] for t in recipients if out[t] < SINGLE_CAP - 1e-12}
            base = sum(eligible.values()) or float(len(eligible))
            if not eligible:
                break
            give = min(freed, sum(SINGLE_CAP - v for v in eligible.values()))
            for t in eligible:
                share = (out[t] / base) if sum(eligible.values()) > 1e-12 else (1.0 / len(eligible))
                out[t] = min(SINGLE_CAP, out[t] + give * share)
            freed -= give
    # Renormalize to sum=1 by scaling ONLY non-cluster positions, so a saturated
    # water-fill (recipients all at SINGLE_CAP) cannot re-inflate the capped cluster
    # above `cap`. If non-cluster mass is degenerate (≈0), fall back to a full
    # renormalize — that case is structurally infeasible {cluster≤cap, 단일≤cap, 합=1}.
    s = sum(out.values())
    if abs(s - 1.0) > FLOAT_TOLERANCE and s > 0:
        non_cluster = [t for t in out if t not in all_cluster_members]
        nc_sum = sum(out[t] for t in non_cluster)
        target_nc = nc_sum + (1.0 - s)
        if nc_sum > 1e-12 and target_nc > 0:
            f = target_nc / nc_sum
            for t in non_cluster:
                out[t] *= f
        else:
            return {t: w / s for t, w in out.items()}
    return dict(out)
