"""Mandate Validator — runs all 4 deterministic checks + integrity pre-check.

Stage 5 정리 (Commit A):
  ① correlation severity hard 승격 (correlation_check.py)
  ② risk_asset 정의 통일 — BUCKET_TO_CATEGORIES 명시 매핑 (concentration_check.py)
  ③ Weight integrity NaN/Inf 사전 검증 (이 모듈에서)
  ④ turnover_check days_remaining 제거 (turnover_check.py)
  ⑤ Explicit RebalanceMode + FLOOR_BY_MODE dict (이 모듈에서)
"""
import math
from pathlib import Path

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.mandate import (
    RebalanceMode, ValidationReport, Violation,
)
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.mandate.concentration_check import validate_concentration
from tradingagents.skills.mandate.correlation_check import (
    validate_correlation_concentration,
)
from tradingagents.skills.mandate.turnover_check import validate_turnover_feasibility
from tradingagents.skills.mandate.universe_check import validate_universe


# Rebalance mode → (turnover floor, days_remaining 참고용).
# 현재 2-mode. daily/weekly 추가는 룰북 / 운영자 결정 후 dict 항목 추가.
FLOOR_BY_MODE: dict[str, tuple[float, int]] = {
    "initial": (0.80, 5),
    "monthly": (0.10, 20),
}


def _check_weight_integrity(wv: WeightVector) -> list[Violation]:
    """Stage 5 정리 ③ — sum≈1.0, w≥0, not NaN/Inf 명시 검증.

    Pydantic WeightVector._normalize가 sum/음수는 잡지만 NaN/Inf는 통과 가능.
    fallback_normalizer는 assert로 검증하지만 정상 path는 부재 → 추가.
    """
    issues: list[Violation] = []

    weights = wv.weights
    if not weights:
        issues.append(Violation(
            rule="weight_validity",
            description="WeightVector.weights is empty",
            severity="hard",
            suggested_fix="Re-run Allocator",
        ))
        return issues

    bad_values: list[str] = []
    for t, w in weights.items():
        if not isinstance(w, (int, float)):
            bad_values.append(f"{t}={w!r} (non-numeric)")
            continue
        wf = float(w)
        if math.isnan(wf) or math.isinf(wf):
            bad_values.append(f"{t}={wf} (NaN/Inf)")
        elif wf < 0:
            bad_values.append(f"{t}={wf:.4f} (negative)")

    if bad_values:
        issues.append(Violation(
            rule="weight_validity",
            description=f"Invalid weights: {'; '.join(bad_values[:5])}",
            severity="hard",
            suggested_fix="Re-run Allocator with constrained optimization",
        ))

    total = sum(float(w) for w in weights.values() if isinstance(w, (int, float)))
    if math.isnan(total) or math.isinf(total) or abs(total - 1.0) > 1e-3:
        issues.append(Violation(
            rule="weight_sum",
            description=f"Weight sum {total} not ≈ 1.0 (tolerance 1e-3)",
            severity="hard",
            suggested_fix="Re-normalize weights",
        ))

    return issues


def _resolve_rebalance_mode(state) -> RebalanceMode:
    """explicit state["rebalance_mode"] 우선, 없으면 previous_portfolio
    유무로 backward-compat 분기.
    """
    explicit = state.get("rebalance_mode")
    if explicit in FLOOR_BY_MODE:
        return explicit  # type: ignore[return-value]
    return "monthly" if state.get("previous_portfolio") else "initial"


def create_mandate_validator():
    """Factory for Mandate Validator node.

    Returns a node function that:
    - Pre-check: weight integrity (sum=1, w≥0, not NaN/Inf)
    - Runs 4 deterministic checks (universe, concentration, correlation, turnover)
    - Returns state updates with validation_passed bool and allocation_feedback
      (hard violations only).
    """
    def node(state):
        weights = state.get("weight_vector")
        if weights is None:
            return {
                "validation_passed": False,
                "validation_report": ValidationReport(
                    passed=False,
                    violations=[Violation(
                        rule="weight_validity",
                        description="No weight_vector to validate",
                        severity="hard",
                        suggested_fix="Re-run Allocator",
                    )],
                ),
                "allocation_feedback": [],
            }

        all_violations: list[Violation] = []

        # ③ integrity pre-check
        integrity_issues = _check_weight_integrity(weights)
        all_violations.extend(integrity_issues)

        # integrity violation이 hard면 다른 check 의미 없음 → 즉시 반환
        if any(v.severity == "hard" for v in integrity_issues):
            report = ValidationReport(passed=False, violations=all_violations)
            return {
                "validation_report": report,
                "validation_passed": False,
                "allocation_feedback": report.hard_violations,
            }

        universe = load_universe(Path(state["universe_path"]))

        universe_result = validate_universe(weights, universe)
        all_violations.extend(universe_result.violations)

        concentration_result = validate_concentration(weights, universe)
        all_violations.extend(concentration_result.violations)

        correlation_clusters = state.get("correlation_clusters", [])
        correlation_result = validate_correlation_concentration(
            weights, correlation_clusters,
        )
        all_violations.extend(correlation_result.violations)

        # ⑤ Rebalance mode 명시 분기
        mode = _resolve_rebalance_mode(state)
        floor_pct, _days = FLOOR_BY_MODE[mode]

        previous_portfolio = state.get("previous_portfolio")
        prev_weights = (
            previous_portfolio.get("weights") if previous_portfolio else None
        )
        turnover_result = validate_turnover_feasibility(
            weights, prev_weights, state["capital_krw"],
            floor_pct=floor_pct,
        )
        all_violations.extend(turnover_result.violations)

        report = ValidationReport(
            passed=not any(v.severity == "hard" for v in all_violations),
            violations=all_violations,
        )
        return {
            "validation_report": report,
            "validation_passed": report.passed,
            "allocation_feedback": (
                report.hard_violations if not report.passed else []
            ),
            "rebalance_mode": mode,
        }

    return node
