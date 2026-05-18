from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.schemas.technical import Cluster
from tradingagents.skills.mandate.correlation_check import validate_correlation_concentration


def test_cluster_under_cap_passes():
    weights = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A1": 0.10, "A2": 0.10, "A3": 0.10, "A4": 0.70},
        rationale="x",
    )
    clusters = [
        Cluster(cluster_id="ai", members=["A1", "A2"],
                avg_internal_correlation=0.85, category_label="AI/Semi"),
    ]
    rep = validate_correlation_concentration(weights, clusters, cluster_cap=0.25)
    assert rep.passed is True


def test_cluster_over_cap_fails_hard():
    """Stage 5 정리 ①: cluster cap 위반은 hard severity로 승격됨."""
    weights = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A1": 0.18, "A2": 0.15, "A3": 0.07, "A4": 0.60},
        rationale="x",
    )
    clusters = [
        Cluster(cluster_id="ai", members=["A1", "A2", "A3"],
                avg_internal_correlation=0.85, category_label="AI/Semi"),
    ]
    rep = validate_correlation_concentration(weights, clusters, cluster_cap=0.25)
    assert rep.passed is False
    assert rep.violations[0].severity == "hard"
    assert rep.violations[0].rule == "correlation_concentration"
