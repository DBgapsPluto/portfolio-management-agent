"""Turnover floor check — 회전율 최소치 충족 여부.

대회 회전율 정의 (docs/competition-rules-summary.md §3):
    turnover = (매수금액 + 매도금액) / 평균자산,  평균자산 = (기초자산 + 기말자산) / 2

즉 매도/매수 양쪽을 합산하는 "total trade volume" 정의이며, 이것이 곧 대회
공식이다 — 대안 정의로의 마이그레이션 여지가 있는 "2배 카운트"가 아니다
(2026-08-15 fix-tier G3에서 룰북 §3 원문과 일치 확인, "2배 모호성" 해소;
당시 플랜 문서는 git 태그 docs-archive-2026-08에 보존). floor 값이 이
정의에 맞춰 calibrated되어 있음:
    initial (5/28 → 6/8): floor=0.80, 5 영업일
    monthly:               floor=0.10, 20 영업일

`days_remaining` 인자는 본문에서 사용하지 않음 → 시그니처에서 제거.
"""
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.registry import register_skill


# Stage 5 audit (2026-05-26, Task 1): named tolerance.
# turnover 비교는 weight 차이의 합 → 더 작은 tolerance (1e-9) 사용.
TURNOVER_TOLERANCE: float = 1e-9

_CASH = "CASH"


@register_skill(name="validate_turnover_feasibility", category="mandate")
def validate_turnover_feasibility(
    proposed: WeightVector,
    previous_weights: dict[str, float] | None,
    capital_krw: int,
    floor_pct: float,
    trade_turnover: float | None = None,
) -> ValidationReport:
    """Check if proposed weights produce ≥floor_pct turnover.

    Turnover 정의: (buy + sell) / avg_assets (현재 시스템 calibration).

    For initial setup (5/28 → 6/8): floor_pct=0.80.
    For monthly: floor_pct=0.10.

    권위 (F3 감사 MF-5/MF-6):
      - previous_weights is None (initial) → 전량 매수라 weight 기반 = 체결 기반과
        동치 — 사실상 항진(tautological). trade_turnover 는 무시.
      - previous_weights 있고 trade_turnover 제공 → 그 값이 월간 floor 의 유일한
        권위(엔진이 계산한 체결 명목, plan_out["turnover"]). weight-delta 재유도는
        하지 않는다 — 가격 드리프트만으로 거래 없이도 floor 충족 착시가 생기기 때문.
      - previous_weights 있고 trade_turnover 미제공(그래프 단계 등 체결 전) →
        weight-delta 근사(advisory 용도, 호출부에서 severity 조정). CASH 는 delta
        집계에서 제외 — full_wv 는 CASH 를 포함하지만 previous_weights 는 관행상
        CASH 항목을 담지 않아, 포함 시 잔여현금 자체가 '거래'로 잡히는 phantom
        turnover 가 생긴다 (감사 MF-6).
    """
    avg_assets = capital_krw  # simplified — actual AUM은 daily NAV 적분
    cash_phantom_excluded = False
    if previous_weights is None:
        # Initial: all weights are buys
        buy_amount = sum(proposed.weights.values()) * capital_krw
        sell_amount = 0
        turnover = (buy_amount + sell_amount) / avg_assets
    elif trade_turnover is not None:
        turnover = trade_turnover
    else:
        all_tickers = (set(proposed.weights) | set(previous_weights)) - {_CASH}
        cash_phantom_excluded = _CASH in proposed.weights or _CASH in previous_weights
        delta = {
            t: proposed.weights.get(t, 0) - previous_weights.get(t, 0)
            for t in all_tickers
        }
        buy_amount = sum(d for d in delta.values() if d > 0) * capital_krw
        sell_amount = -sum(d for d in delta.values() if d < 0) * capital_krw
        turnover = (buy_amount + sell_amount) / avg_assets

    violations = []
    if turnover < floor_pct - TURNOVER_TOLERANCE:
        description = f"Planned turnover {turnover:.4f} < floor {floor_pct}"
        if cash_phantom_excluded:
            description += " (CASH phantom delta excluded — MF-6)"
        violations.append(Violation(
            rule="turnover_floor",
            description=description,
            severity="hard",
            suggested_fix=f"Increase trade size by {(floor_pct - turnover):.4f}",
        ))
    return ValidationReport(passed=not violations, violations=violations)


def compute_trade_turnover(
    *, buy_krw: float, sell_krw: float, begin_value: float, end_value: float,
) -> float:
    """체결 명목 기반 turnover = (buy+sell) / 평균자산(begin,end 평균).

    §C2 월누적(month-to-date) 집계 전용 헬퍼. per-plan 분모 개선안(avg(begin,end)
    로 build_rebalance_plan 의 분모를 바꾸자는 제안)은 철회됨 — denom = invested +
    cash_residual == current_value 가 항등임이 감사 MF-6 로 증명되어 단일 plan 에는
    아무 효과가 없다. 여러 plan 에 걸친 buy_krw/sell_krw 합과 begin/end_value 평균을
    합성하는 월누적 집계에서만 의미가 있다.
    """
    denom = (begin_value + end_value) / 2
    if denom <= 0:
        return 0.0
    return (buy_krw + sell_krw) / denom
