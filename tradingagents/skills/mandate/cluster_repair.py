"""상관군집 cap deterministic repair (군집합 ≤ cap). self-imposed 35% (대회 규칙 아님).

trader 노드가 ETF weight 확정 후 호출. 초과 군집 멤버를 비례 축소, freed 를
"현재 위반(초과) 군집의 멤버가 아닌" 포지션에 water-fill(단일 20% 한도), 수혜
포화 시 잔여는 CASH 적립(무제한 최후 목적지 — overlay._water_fill 미러).
순수·결정론. correlation_check(validator) 와 동일 임계.

D1-2 (F5/MF-1): 전수 그래프에선 대부분 종목이 '어떤' 군집엔 속하므로 구
수혜 풀("어느 군집에도 없는")은 붕괴한다 — 비위반 군집 멤버도 정당한 수혜자.
또한 구 코드의 포화 폴백(전체 renormalize)은 방금 cap 으로 눌러놓은 군집을
비례로 재팽창시켜 위반을 복원했다(감사 MF-1 체인 ②) → CASH 적립으로 대체.
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
        # D1-2(a): 수혜 풀 = "현재 초과(위반) 상태인 군집"의 멤버가 아닌 전 종목.
        # 스케일 전에 평가하므로 지금 수선 중인 군집 멤버도 자동 제외된다. 비위반
        # 군집 멤버로의 spill 이 그 군집을 한 패스 안에서 cap 초과로 밀 수 있는데,
        # 이는 의도적으로 바깥 교대 루프(_repair_all_weights x12 in trader_allocator,
        # daily_full 의 수선 x3 루프)가 cluster repair 를 재실행해 잡는 것에 의존한다.
        over_cap_members: set[str] = set()
        for c in clusters:
            if sum(out.get(m, 0.0) for m in c.members) > cap + FLOAT_TOLERANCE:
                over_cap_members.update(c.members)
        scale = cap / csum
        for t in members:
            out[t] *= scale
        freed = csum - cap
        recipients = [t for t in out if t not in over_cap_members]
        for _ in range(_MAX_ITERS):
            if freed <= 1e-12:
                break
            eligible = {t: out[t] for t in recipients if out[t] < SINGLE_CAP - 1e-12}
            base = sum(eligible.values()) or float(len(eligible))
            if not eligible:
                break
            give = min(freed, sum(SINGLE_CAP - v for v in eligible.values()))
            dist = 0.0
            for t in eligible:
                share = (out[t] / base) if sum(eligible.values()) > 1e-12 else (1.0 / len(eligible))
                before = out[t]
                out[t] = min(SINGLE_CAP, out[t] + give * share)
                dist += out[t] - before
            # give is only this round's intended cap — uneven headroom (vs. weight-proportional
            # share) can clip an individual ticker below its full share. Subtract the ACTUALLY
            # distributed amount (dist), not give, so the clipped remainder reaches the next
            # iteration's still-eligible recipients (mirrors overlay._water_fill / risk_repair
            # fix) instead of vanishing — a loss small enough to slip under this file's own
            # FLOAT_TOLERANCE and skip the sum-restore safety net below entirely.
            freed -= dist
        # D1-2(b): 수혜 포화 → 잔여를 CASH 에 적립(add-not-overwrite — overlay 의
        # 0d51a75 수정 미러). CASH 는 SINGLE_CAP 면제인 무제한 최후 목적지. 구
        # 코드는 이 잔여를 하단 sum-restore 의 전체-renormalize 폴백으로 넘겨
        # 방금 cap 으로 누른 군집을 재팽창시켰다(위반 복원 — 감사 MF-1 체인 ②).
        if freed > 1e-12:
            out["CASH"] = out.get("CASH", 0.0) + freed
    # Restore sum=1 by water-filling the leftover deficit into non-cluster positions
    # UNDER SINGLE_CAP (same loop pattern as the cluster water-fill above), so a
    # saturated water-fill cannot re-inflate the capped cluster AND cannot emit a single
    # non-cluster ETF above SINGLE_CAP. Only when the deficit exceeds total non-cluster
    # headroom — structurally infeasible {cluster≤cap, 단일≤cap, 합=1} — fall back to a
    # full renormalize (matches repair_risk_cap's documented degenerate fallback; the
    # cluster may re-inflate slightly, acceptable only in that genuinely infeasible case).
    s = sum(out.values())
    if abs(s - 1.0) > FLOAT_TOLERANCE and s > 0:
        non_cluster = [t for t in out if t not in all_cluster_members]
        deficit = 1.0 - s                      # > 0 when recipients saturated during cluster water-fill
        nc_room = sum(SINGLE_CAP - out[t] for t in non_cluster if out[t] < SINGLE_CAP)
        if deficit > 1e-12 and nc_room > 1e-12 and deficit <= nc_room + 1e-12:
            for _ in range(_MAX_ITERS):
                if deficit <= 1e-12:
                    break
                eligible = {t: out[t] for t in non_cluster if out[t] < SINGLE_CAP - 1e-12}
                if not eligible:
                    break
                tot = sum(eligible.values())
                give = min(deficit, sum(SINGLE_CAP - v for v in eligible.values()))
                placed = 0.0
                for t in eligible:
                    share = (out[t] / tot) if tot > 1e-12 else (1.0 / len(eligible))
                    before = out[t]
                    out[t] = min(SINGLE_CAP, out[t] + give * share)
                    placed += out[t] - before   # only count mass that fit under SINGLE_CAP
                deficit -= placed
            return dict(out)
        # truly infeasible {cluster≤cap, 단일≤cap, 합=1}: full renormalize
        return {t: w / s for t, w in out.items()}
    return dict(out)
