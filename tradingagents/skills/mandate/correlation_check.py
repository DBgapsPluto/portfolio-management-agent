from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.schemas.technical import Cluster
from tradingagents.skills.registry import register_skill


# Stage 5 audit (2026-05-26, Task 1): named const.
# self-imposed (DB GAPS 규칙엔 cluster cap 없음; A2 35% 완화) — validator/repair 동기화.
DEFAULT_CLUSTER_CAP: float = 0.35
FLOAT_TOLERANCE: float = 1e-6


@register_skill(name="validate_correlation_concentration", category="mandate")
def validate_correlation_concentration(
    weights: WeightVector, clusters: list[Cluster],
    cluster_cap: float = DEFAULT_CLUSTER_CAP,
) -> ValidationReport:
    """Single correlation cluster (e.g., AI/semi) sum should ≤ cluster_cap.

    Severity = "hard" — Stage 5 정리에서 승격 (이전 "soft"는 D4 retry 발동 X
    였음). 우리 시스템 내에서는 mandate-level로 강제. Stage 4 concentration_lens
    가 더 strict한 cap만 추가 (책임 분리, 옵션 A-1).
    """
    violations = []
    for cluster in clusters:
        cluster_sum = sum(weights.weights.get(t, 0) for t in cluster.members)
        if cluster_sum > cluster_cap + FLOAT_TOLERANCE:
            violations.append(Violation(
                rule="correlation_concentration",
                description=(
                    f"Cluster '{cluster.category_label}' sum {cluster_sum:.4f} > {cluster_cap} "
                    f"({len(cluster.members)} members, avg corr {cluster.avg_internal_correlation:.2f})"
                ),
                severity="hard",
                suggested_fix=f"Reduce concentration in {cluster.category_label}",
            ))
    return ValidationReport(passed=not violations, violations=violations)
