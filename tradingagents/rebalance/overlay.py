"""daily/event 결정론 방어 오버레이 (스펙 §6.1). 종목 불변, 비중만 조정. LLM 0."""
from collections.abc import Callable

from tradingagents.skills.mandate.concentration_check import FLOAT_TOLERANCE


def defensive_overlay(weights: dict[str, float], is_risk: Callable[[str], bool],
                      defensive_target: float) -> dict[str, float]:
    """위험자산을 defensive_target 까지 축소 + 안전자산 비례 water-fill.

    risk_sum ≤ defensive_target 이면 무변경(noop). 초과 시 위험 비례 축소,
    freed 를 안전자산에 비례 분배 후 정규화.
    """
    risk_sum = sum(w for t, w in weights.items() if is_risk(t))
    if risk_sum <= defensive_target + FLOAT_TOLERANCE:
        return dict(weights)

    safe_sum = sum(w for t, w in weights.items() if not is_risk(t))
    new_risk = defensive_target
    rf = new_risk / risk_sum
    sf = (1.0 - new_risk) / safe_sum if safe_sum > 0 else 1.0
    out = {t: (w * rf if is_risk(t) else w * sf) for t, w in weights.items()}
    total = sum(out.values())
    return {t: w / total for t, w in out.items()}


def risk_on_overlay(weights: dict[str, float], is_risk: Callable[[str], bool],
                    step: float, hard_cap: float = 0.70) -> dict[str, float]:
    """위험자산을 step 만큼 확대(hard_cap 내). 위험·안전 비례 조정 후 정규화."""
    risk_sum = sum(w for t, w in weights.items() if is_risk(t))
    safe_sum = sum(w for t, w in weights.items() if not is_risk(t))
    if risk_sum <= 0 or safe_sum <= 0:
        return dict(weights)
    new_risk = min(risk_sum + step, hard_cap)
    rf = new_risk / risk_sum
    sf = (1.0 - new_risk) / safe_sum
    out = {t: (w * rf if is_risk(t) else w * sf) for t, w in weights.items()}
    total = sum(out.values())
    return {t: w / total for t, w in out.items()}
