"""조건부 재진단(reassess) target — macro+risk 재실행 → bucket tilt → 비례 스케일 (스펙 §6.2).

종목 교체 0(보유 우선 극대화): 직전 ETF weights 를 위험/안전 그룹 비례로만 조정.
"""
from collections.abc import Callable

from tradingagents.rebalance.weekly_tilt import run as weekly_run


def reassess_target(current: dict[str, float], is_risk: Callable[[str], bool],
                    as_of: str, previous_path: str | None) -> dict[str, float] | None:
    """regime 변화 시 위험/안전 비례 스케일 target, 변화 없거나 delta=0 이면 None."""
    result = weekly_run(as_of=as_of, previous_path=previous_path)
    if not result.regime_changed:
        return None
    delta = result.tilt_proposed.get("risk_asset_delta", 0.0)
    if delta == 0.0:
        return None
    stock = {t: w for t, w in current.items() if t != "CASH"}
    risk_sum = sum(w for t, w in stock.items() if is_risk(t))
    safe_sum = sum(w for t, w in stock.items() if not is_risk(t))
    if risk_sum <= 0 or safe_sum <= 0:
        return None
    new_risk = max(0.0, min(risk_sum + delta, 0.70))
    rf = new_risk / risk_sum
    sf = (1.0 - new_risk) / safe_sum
    out = {t: (w * rf if is_risk(t) else w * sf) for t, w in stock.items()}
    total = sum(out.values())
    return {t: w / total for t, w in out.items()}
