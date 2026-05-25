"""Turnover floor check — 회전율 최소치 충족 여부.

Turnover 정의 (현재 시스템):
    turnover = (buy_amount + sell_amount) / avg_assets
즉 "total trade volume" 정의로 매도/매수 양쪽을 합산 (2배 카운트).
이 정의에 맞춰 floor 값이 calibrated되어 있음:
    initial (5/28 → 6/8): floor=0.80, 5 영업일
    monthly:               floor=0.10, 20 영업일

업계 표준 'two-side average' `(buy+sell)/2/AUM`로 바꾸려면 floor도 절반으로
조정 필요. 현재는 시스템 내에서 self-consistent하게 유지 (대회 §3.1 룰북
확인 후 마이그레이션 가능).

`days_remaining` 인자는 본문에서 사용하지 않음 → 시그니처에서 제거.
"""
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.registry import register_skill


# Stage 5 audit (2026-05-26, Task 1): named tolerance.
# turnover 비교는 weight 차이의 합 → 더 작은 tolerance (1e-9) 사용.
TURNOVER_TOLERANCE: float = 1e-9


@register_skill(name="validate_turnover_feasibility", category="mandate")
def validate_turnover_feasibility(
    proposed: WeightVector,
    previous_weights: dict[str, float] | None,
    capital_krw: int,
    floor_pct: float,
) -> ValidationReport:
    """Check if proposed weights produce ≥floor_pct turnover.

    Turnover 정의: (buy + sell) / avg_assets (현재 시스템 calibration).

    For initial setup (5/28 → 6/8): floor_pct=0.80.
    For monthly: floor_pct=0.10.
    """
    if previous_weights is None:
        # Initial: all weights are buys
        buy_amount = sum(proposed.weights.values()) * capital_krw
        sell_amount = 0
    else:
        all_tickers = set(proposed.weights) | set(previous_weights)
        delta = {
            t: proposed.weights.get(t, 0) - previous_weights.get(t, 0)
            for t in all_tickers
        }
        buy_amount = sum(d for d in delta.values() if d > 0) * capital_krw
        sell_amount = -sum(d for d in delta.values() if d < 0) * capital_krw

    avg_assets = capital_krw  # simplified — actual AUM은 daily NAV 적분
    turnover = (buy_amount + sell_amount) / avg_assets

    violations = []
    if turnover < floor_pct - TURNOVER_TOLERANCE:
        violations.append(Violation(
            rule="turnover_floor",
            description=f"Planned turnover {turnover:.4f} < floor {floor_pct}",
            severity="hard",
            suggested_fix=f"Increase trade size by {(floor_pct - turnover):.4f}",
        ))
    return ValidationReport(passed=not violations, violations=violations)
