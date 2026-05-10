from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.schemas.technical import Cluster
from tradingagents.skills.registry import register_skill


@register_skill(name="validate_correlation_concentration", category="mandate")
def validate_correlation_concentration(
    weights: WeightVector, clusters: list[Cluster],
    cluster_cap: float = 0.25,
) -> ValidationReport:
    """Single correlation cluster (e.g., AI/semi) sum should ≤ cluster_cap.

    Per design D6: 70-point evaluation core 'single risk control'. Soft severity
    because it's evaluator-critical but not a hard mandate rule like §2.2 caps.
    """
    violations = []
    for cluster in clusters:
        cluster_sum = sum(weights.weights.get(t, 0) for t in cluster.members)
        if cluster_sum > cluster_cap:
            violations.append(Violation(
                rule="correlation_concentration",
                description=(
                    f"Cluster '{cluster.category_label}' sum {cluster_sum:.4f} > {cluster_cap} "
                    f"({len(cluster.members)} members, avg corr {cluster.avg_internal_correlation:.2f})"
                ),
                severity="soft",
                suggested_fix=f"Reduce concentration in {cluster.category_label}",
            ))
    return ValidationReport(passed=not violations, violations=violations)
