"""Mandate Validator — runs all 4 deterministic checks + integrity pre-check.

Stage 5 정리 (Commit A):
  ① correlation severity hard 승격 (correlation_check.py)
  ② risk_asset 정의 통일 — BUCKET_TO_CATEGORIES 명시 매핑 (concentration_check.py)
  ③ Weight integrity NaN/Inf 사전 검증 (이 모듈에서)
  ④ turnover_check days_remaining 제거 (turnover_check.py)
  ⑤ Explicit RebalanceMode + FLOOR_BY_MODE dict (이 모듈에서)
"""
import logging
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

logger = logging.getLogger(__name__)


# Stage 5 audit (2026-05-26, Task 1): named const.
TURNOVER_FLOOR_INITIAL: float = 0.80   # 5/28 → 6/8 initial rebalance
TURNOVER_FLOOR_MONTHLY: float = 0.10   # monthly cadence
INITIAL_DAYS_REMAINING_PROXY: int = 5  # info only
MONTHLY_DAYS_REMAINING_PROXY: int = 20

WEIGHT_SUM_TOLERANCE: float = 1e-3     # weight_vector 통합 sum=1.0 허용 오차

# Rebalance mode → (turnover floor, days_remaining 참고용).
# 현재 2-mode. daily/weekly 추가는 룰북 / 운영자 결정 후 dict 항목 추가.
FLOOR_BY_MODE: dict[str, tuple[float, int]] = {
    "initial": (TURNOVER_FLOOR_INITIAL, INITIAL_DAYS_REMAINING_PROXY),
    "monthly": (TURNOVER_FLOOR_MONTHLY, MONTHLY_DAYS_REMAINING_PROXY),
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
    if math.isnan(total) or math.isinf(total) or abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        issues.append(Violation(
            rule="weight_sum",
            description=(
                f"Weight sum {total} not ≈ 1.0 (tolerance {WEIGHT_SUM_TOLERANCE})"
            ),
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
        attempts = state.get("allocation_attempts", 0)
        logger.info(
            "mandate_validator start: n_positions=%s, attempts=%d",
            len(weights.weights) if weights else 0, attempts,
        )

        # Stage 5 audit Task 0: attribution dict — Stage 6 narrative 가시화.
        mv_attribution: dict = {
            "input_present": {
                "weight_vector":   weights is not None,
                "universe_path":   state.get("universe_path") is not None,
                "capital_krw":     state.get("capital_krw") is not None,
                "previous_portfolio": state.get("previous_portfolio") is not None,
                "correlation_clusters": bool(state.get("correlation_clusters")),
            },
            "attempts": attempts,
        }

        if weights is None:
            logger.warning("mandate_validator: weight_vector 없음 → fail-fast")
            mv_attribution["skipped"] = "weight_vector_missing"
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
                "mandate_validator_attribution": mv_attribution,
            }

        all_violations: list[Violation] = []
        check_counts: dict[str, dict[str, int]] = {}

        # ③ integrity pre-check
        integrity_issues = _check_weight_integrity(weights)
        all_violations.extend(integrity_issues)
        check_counts["integrity"] = {
            "hard": sum(1 for v in integrity_issues if v.severity == "hard"),
            "soft": sum(1 for v in integrity_issues if v.severity != "hard"),
        }

        # integrity violation이 hard면 다른 check 의미 없음 → 즉시 반환
        if any(v.severity == "hard" for v in integrity_issues):
            logger.warning(
                "mandate_validator: integrity pre-check fail (%d hard) → skip 4 checks",
                check_counts["integrity"]["hard"],
            )
            mv_attribution["check_counts"] = check_counts
            mv_attribution["hard_violations"] = [
                {"rule": v.rule, "description": v.description[:200]}
                for v in integrity_issues if v.severity == "hard"
            ][:3]
            report = ValidationReport(passed=False, violations=all_violations)
            return {
                "validation_report": report,
                "validation_passed": False,
                "allocation_feedback": report.hard_violations,
                "mandate_validator_attribution": mv_attribution,
            }

        universe = load_universe(Path(state["universe_path"]))

        universe_result = validate_universe(weights, universe)
        all_violations.extend(universe_result.violations)
        check_counts["universe"] = {
            "hard": sum(1 for v in universe_result.violations if v.severity == "hard"),
            "soft": sum(1 for v in universe_result.violations if v.severity != "hard"),
        }

        concentration_result = validate_concentration(weights, universe)
        all_violations.extend(concentration_result.violations)
        check_counts["concentration"] = {
            "hard": sum(1 for v in concentration_result.violations if v.severity == "hard"),
            "soft": sum(1 for v in concentration_result.violations if v.severity != "hard"),
        }

        correlation_clusters = state.get("correlation_clusters", [])
        correlation_result = validate_correlation_concentration(
            weights, correlation_clusters,
        )
        all_violations.extend(correlation_result.violations)
        check_counts["correlation"] = {
            "hard": sum(1 for v in correlation_result.violations if v.severity == "hard"),
            "soft": sum(1 for v in correlation_result.violations if v.severity != "hard"),
        }

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
        check_counts["turnover"] = {
            "hard": sum(1 for v in turnover_result.violations if v.severity == "hard"),
            "soft": sum(1 for v in turnover_result.violations if v.severity != "hard"),
        }

        report = ValidationReport(
            passed=not any(v.severity == "hard" for v in all_violations),
            violations=all_violations,
        )

        # Stage 5 audit Task 0: per-check 결과 + 최종 verdict logger.
        for name, counts in check_counts.items():
            if counts["hard"] > 0 or counts["soft"] > 0:
                logger.info(
                    "mandate_validator: %s check — hard=%d, soft=%d",
                    name, counts["hard"], counts["soft"],
                )
        logger.info(
            "mandate_validator complete: passed=%s, rebalance_mode=%s, "
            "total_violations=%d (hard=%d)",
            report.passed, mode, len(all_violations),
            sum(c["hard"] for c in check_counts.values()),
        )

        mv_attribution["check_counts"] = check_counts
        mv_attribution["rebalance_mode"] = mode
        mv_attribution["turnover_floor"] = floor_pct
        mv_attribution["validation_passed"] = report.passed
        mv_attribution["hard_violations"] = [
            {
                "rule": v.rule,
                "description": v.description[:200],
                "suggested_fix": v.suggested_fix[:100] if v.suggested_fix else None,
            }
            for v in all_violations if v.severity == "hard"
        ][:5]
        return {
            "validation_report": report,
            "validation_passed": report.passed,
            "allocation_feedback": (
                report.hard_violations if not report.passed else []
            ),
            "rebalance_mode": mode,
            "mandate_validator_attribution": mv_attribution,
        }

    return node
