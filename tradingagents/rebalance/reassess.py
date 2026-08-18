"""조건부 재진단(reassess) target — macro+risk 재실행 → bucket tilt → 비례 스케일 (스펙 §6.2).

종목 교체 0(보유 우선 극대화): 직전 ETF weights 를 위험/안전 그룹 비례로만 조정.
"""
from collections.abc import Callable

from tradingagents.rebalance.weekly_tilt import run as weekly_run


def reassess_target(current: dict[str, float], is_risk: Callable[[str], bool],
                    as_of: str, previous_path: str | None,
                    sell_ok: Callable[[str], bool] | None = None) -> dict[str, float] | None:
    """regime 변화 시 위험/안전 비례 스케일 target, 변화 없거나 delta=0 이면 None.

    F1/B3(MF-9): risk 축소(delta<0)에서만 sell_ok=False 위험자산(위기 보호, 예: 금)을 rf
    스케일 대상에서 제외 — 원 비중을 정확히 유지한다(보호분 제외 나머지로 예산을
    재분배, 최종 합은 항상 1.0). sell_ok 는 매도 가능 여부이므로 risk 확대(delta>0)에는
    적용하지 않는다 — 확대는 매도가 아니다. 70% 위험자산 hard cap 은 두 방향 모두
    (보호분 포함) 전체 기준으로 여전히 적용된다.
    """
    result = weekly_run(as_of=as_of, previous_path=previous_path)
    if not result.regime_changed:
        return None
    delta = result.tilt_proposed.get("risk_asset_delta", 0.0)
    if delta == 0.0:
        return None
    # sell_ok 는 축소(delta<0)에서만 적용 — 방향-무관하게 걸면 보호 버킷뿐인 book 의
    # risk-ON 이 scalable_sum<=0 으로 전량 사라진다(아래 None 분기).
    _sell_ok = sell_ok if (sell_ok and delta < 0) else (lambda t: True)
    stock = {t: w for t, w in current.items() if t != "CASH"}
    protected = {t: w for t, w in stock.items() if is_risk(t) and not _sell_ok(t)}
    scalable = {t: w for t, w in stock.items() if is_risk(t) and _sell_ok(t)}
    safe = {t: w for t, w in stock.items() if not is_risk(t)}
    protected_sum = sum(protected.values())
    scalable_sum = sum(scalable.values())
    safe_sum = sum(safe.values())
    if scalable_sum <= 0 or safe_sum <= 0:
        return None
    target_scalable = max(0.0, min(scalable_sum + delta, 0.70 - protected_sum))
    rf = target_scalable / scalable_sum
    new_total_risk = protected_sum + target_scalable
    sf = (1.0 - new_total_risk) / safe_sum
    out = dict(protected)
    out.update({t: w * rf for t, w in scalable.items()})
    out.update({t: w * sf for t, w in safe.items()})
    total = sum(out.values())
    return {t: w / total for t, w in out.items()}
