"""daily/event 결정론 방어 오버레이 (스펙 §6.1). 종목 불변, 비중만 조정. LLM 0."""
import logging
from collections.abc import Callable

from tradingagents.skills.mandate.concentration_check import FLOAT_TOLERANCE
from tradingagents.skills.portfolio.within_bucket import SINGLE_CAP

logger = logging.getLogger(__name__)

_MAX_ITERS: int = 50


def _water_fill(base: dict[str, float], freed: float, single_cap: float) -> dict[str, float]:
    """freed 를 base(목적지 후보, CASH 포함 가능) 에 헤드룸-인지 비례 분배.

    single_cap 포화분은 CASH 로 적립(최후 목적지, 무제한) — risk_repair.py:44-58 패턴 미러.
    """
    out = dict(base)
    overflow = 0.0
    for _ in range(_MAX_ITERS):
        if freed <= 1e-12:
            break
        eligible = {t: v for t, v in out.items() if t != "CASH" and v < single_cap - 1e-12}
        base_sum = sum(eligible.values())
        if base_sum <= 1e-12:
            overflow += freed
            freed = 0.0
            break
        give = min(freed, sum(single_cap - v for v in eligible.values()))
        dist = 0.0
        for t, v in eligible.items():
            delta = give * v / base_sum
            room = single_cap - out[t]
            add = min(delta, room)
            out[t] += add
            dist += add
        # give 는 상한(의도)일 뿐 — 헤드룸이 비중에 비례하지 않으면 delta 가 개별 room 을 넘겨
        # 클리핑된다. 실제로 분배된 dist 만큼만 차감해야 잘린 잔여가 다음 반복(포화 티커 제외된
        # 새 eligible)으로 넘어가거나 최종적으로 overflow→CASH 에 도달한다. give 로 차감하면
        # 클리핑 손실이 freed·overflow 어디에도 반영되지 않고 조용히 사라진다(리뷰 회귀).
        freed -= dist
    overflow += freed
    # CASH 키는 필요할 때만(오버플로 발생, 또는 base 에 이미 존재) 부여 — 무-오버플로 호출부에
    # 스퓨리어스 0.0 CASH 를 주입하지 않는다.
    if overflow > 1e-12 or "CASH" in out:
        out["CASH"] = out.get("CASH", 0.0) + overflow
    return out


def defensive_overlay(weights: dict[str, float], is_risk: Callable[[str], bool],
                      defensive_target: float,
                      sell_ok: Callable[[str], bool] | None = None,
                      dest_ok: Callable[[str], bool] | None = None) -> dict[str, float]:
    """위험자산을 defensive_target 까지 축소 + 안전자산 headroom-인지 water-fill.

    risk_sum ≤ defensive_target 이면 무변경(noop). 초과 시:
      1단계: sell_ok 위험자산만 비례 축소(sell_ok=False 는 원 비중 유지 — 위기 전용 정책,
             F1). freed 를 dest_ok 안전자산에 single-cap(0.20) 헤드룸-인지 물채움, 포화분은
             CASH(최후 목적지, 무제한).
      2단계(가드, 라이브 도달 희박 — CATEGORY_CAPS[FX 및 원자재]=0.20 이 선행 제한): sell_ok
             자산을 0까지 팔고도 defensive_target 미달이면(=보호자산만으로 이미 초과) 보호자산도
             비례 컷 + warning.
    is_risk 는 공식 8-bucket 분류로 불변 — sell_ok/dest_ok 는 그 분할 안에서만 적격성을 좁힌다.
    """
    risk_sum = sum(w for t, w in weights.items() if is_risk(t))
    if risk_sum <= defensive_target + FLOAT_TOLERANCE:
        return dict(weights)

    _sell_ok = sell_ok or (lambda t: True)
    _dest_ok = dest_ok or (lambda t: True)

    protected = {t: w for t, w in weights.items() if is_risk(t) and not _sell_ok(t)}
    scalable = {t: w for t, w in weights.items() if is_risk(t) and _sell_ok(t)}
    safe = {t: w for t, w in weights.items() if not is_risk(t)}
    dest = {t: w for t, w in safe.items() if _dest_ok(t)}
    non_dest_safe = {t: w for t, w in safe.items() if not _dest_ok(t)}

    protected_sum = sum(protected.values())
    scalable_sum = sum(scalable.values())
    if scalable_sum <= 0 and protected_sum <= 0:
        return dict(weights)   # 매도 가능 위험자산 없음 — best-effort no-op

    target_scalable = defensive_target - protected_sum
    if target_scalable < 0:
        # 2단계 가드: 보호자산만으로 이미 target 초과 — sell_ok 자산을 0으로 팔아도 부족하므로
        # 보호자산도 비례 컷한다. 정상 경로 아님(CATEGORY_CAPS 가 선행 제한) — 반드시 경고.
        logger.warning(
            "defensive_overlay: protected risk alone (%.4f) exceeds defensive_target (%.4f) "
            "— cutting protected assets too (guard path, should not occur live)",
            protected_sum, defensive_target,
        )
        pf = defensive_target / protected_sum if protected_sum > 0 else 0.0
        protected = {t: w * pf for t, w in protected.items()}
        scalable = {t: 0.0 for t in scalable}
        target_scalable = 0.0

    rf = (target_scalable / scalable_sum) if scalable_sum > 0 else 1.0
    freed = risk_sum - (sum(protected.values()) + target_scalable)

    dest_out = _water_fill(dest, freed, SINGLE_CAP)

    out: dict[str, float] = {}
    out.update(protected)
    out.update({t: w * rf for t, w in scalable.items()})
    out.update(non_dest_safe)
    out.update(dest_out)
    total = sum(out.values())
    return {t: w / total for t, w in out.items()} if total > 0 else dict(weights)


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
