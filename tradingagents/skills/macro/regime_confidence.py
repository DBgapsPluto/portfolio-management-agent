"""결정론 regime confidence — 신호 일치도 (LLM 자가보고 아님). spec 2026-06-23 §4.

c = growth_agreement × inflation_agreement (Laplace 평활).
각 신호는 부호(+1 확장/인플레 · −1 침체/디스인플레) 투표. stale(sentinel)·None·neutral 기권.
"""
from __future__ import annotations

STALENESS_ABSTAIN = 99   # sentinel 상수 (fetch 성공=0, 실패=99). real-stale 아닌 fetch-fail 게이트.

_QUADRANT_DIR: dict[str, tuple[int, int]] = {
    "growth_inflation":       (+1, +1),
    "growth_disinflation":    (+1, -1),
    "recession_inflation":    (-1, +1),
    "recession_disinflation": (-1, -1),
}


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _fresh(snap) -> bool:
    return snap is not None and getattr(snap, "staleness_days", STALENESS_ABSTAIN) < STALENESS_ABSTAIN


def _growth_votes(s: dict) -> list[int]:
    v: list[int] = []
    us = s.get("us_leading")
    if _fresh(us):
        v.append(-1 if us.recession_signal else _sign(us.cfnai_ma3))
    krl = s.get("kr_leading")
    if _fresh(krl):
        v.append(1 if krl.phase in ("expansion", "peak") else -1)
    kre = s.get("kr_export")
    if _fresh(kre):
        v.append(_sign(kre.yoy_pct))
    krb = s.get("kr_bsi")
    if _fresh(krb):
        v.append(-1 if krb.contraction_signal else _sign(krb.mfg_bsi - 100.0))
    emp = s.get("employment")
    if _fresh(emp):
        v.append(-1 if emp.sahm_rule_triggered else _sign(-emp.rate_change_3mo))
    ra = s.get("risk_appetite")
    if _fresh(ra):
        v.append({"risk_on": 1, "risk_off": -1}.get(ra.signal, 0))
    yc = s.get("yield_curve")
    if _fresh(yc):
        v.append(-1 if yc.spread_10y_2y_bps < 0 else 1)
    cn = s.get("china_leading")
    if _fresh(cn):
        v.append({"expansion": 1, "contraction": -1}.get(cn.realtime_signal, 0))
    gd = s.get("gdp_nowcast")
    if _fresh(gd):
        v.append(_sign(gd.nowcast_pct - 2.0))
    return [x for x in v if x != 0]


def _inflation_votes(s: dict) -> list[int]:
    v: list[int] = []
    infl = s.get("inflation")
    if _fresh(infl):
        v.append(_sign(infl.momentum_3mo - 3.0))
        if infl.core_pce_yoy is not None:
            v.append(_sign(infl.core_pce_yoy - 2.0))
    ie = s.get("inflation_exp")
    if _fresh(ie):
        v.append({"upside": 1, "downside": -1}.get(ie.unanchored_direction, 0))
    cm = s.get("commodity_momentum")
    if _fresh(cm):
        v.append(_sign(cm.wti_3m_pct))
    cc = s.get("chip_cycle")
    if _fresh(cc):
        v.append(1 if cc.accelerating else _sign(cc.chip_ppi_yoy_pct))
    return [x for x in v if x != 0]


def _agreement(votes: list[int], direction: int) -> float:
    n = len(votes)
    if n == 0:
        return 0.0
    k = sum(1 for x in votes if x == direction)
    return (k + 1) / (n + 2)


def compute_regime_confidence(snapshots: dict, quadrant: str) -> float:
    g_dir, i_dir = _QUADRANT_DIR.get(quadrant, (0, 0))
    if g_dir == 0:
        return 0.0
    c = _agreement(_growth_votes(snapshots), g_dir) * _agreement(_inflation_votes(snapshots), i_dir)
    return max(0.0, min(1.0, c))
