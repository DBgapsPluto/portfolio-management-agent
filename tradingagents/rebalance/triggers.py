"""리밸런싱 트리거 라우터 (스펙 §5). LLM 0."""
from collections.abc import Callable

from tradingagents.skills.mandate.concentration_check import HARD_SINGLE_CAP  # noqa: F401 (참조용)
from tradingagents.rebalance.engine import risk_total

# canonical ladder (스펙 §5.4) — 인덱스 작을수록 우선
_LADDER = [
    "event:emergency_defensive", "monthly", "reassess",
    "drift:defensive", "drift:rebalance", "event:risk_on", "alert", "none",
]

_EVENT_TO_TIER = {
    "emergency_defensive_proposal": "event:emergency_defensive",
    "risk_on_proposal": "event:risk_on",
    "rebalance_proposal": "drift:rebalance",
    "alert": "alert",
}


def evaluate_drift(current: dict[str, float], target: dict[str, float],
                   dials: dict, is_risk: Callable[[str], bool]) -> list[str]:
    """현재 보유 비중 기준 드리프트 발화 목록 (CASH 제외)."""
    fired: list[str] = []
    single_abs = dials["single_etf_abs_cap"]
    rel_band = dials["single_etf_rel_band"]
    risk_cap = dials["risk_asset_abs_cap"]
    for t, w in current.items():
        if t == "CASH":
            continue
        tgt = target.get(t, 0.0)
        if (w > single_abs and w > tgt) or abs(w - tgt) > rel_band:
            fired.append("drift:rebalance")
            break
    if risk_total(current, is_risk) > risk_cap:
        fired.append("drift:defensive")
    return fired


def route_tier(event_action: str | None, drift_fired: list[str],
               reassess_fired: bool) -> str:
    """발화들을 canonical ladder 에서 가장 높은 tier 하나로 환원."""
    candidates = set(drift_fired)
    if event_action:
        candidates.add(_EVENT_TO_TIER.get(event_action, "alert"))
    if reassess_fired:
        candidates.add("reassess")
    for tier in _LADDER:
        if tier in candidates:
            return tier
    return "none"
