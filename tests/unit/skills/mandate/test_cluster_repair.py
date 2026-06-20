from tradingagents.schemas.technical import Cluster
from tradingagents.skills.mandate.cluster_repair import repair_cluster_cap, CLUSTER_CAP


def _cl(members):
    return Cluster(cluster_id="1", members=members, avg_internal_correlation=0.8,
                   category_label="semi")


def test_cluster_over_cap_scaled_down():
    w = {"A": 0.25, "B": 0.25, "C": 0.30, "CASH": 0.20}   # A+B=0.50 > 0.35
    out = repair_cluster_cap(w, [_cl(["A", "B"])], cap=0.35)
    assert sum(out[t] for t in ("A", "B")) <= 0.35 + 1e-6
    assert abs(sum(out.values()) - 1.0) < 1e-6


def test_cluster_under_cap_noop():
    w = {"A": 0.15, "B": 0.15, "CASH": 0.70}
    out = repair_cluster_cap(w, [_cl(["A", "B"])], cap=0.35)
    assert out == w


def test_default_cluster_cap_is_035():
    assert CLUSTER_CAP == 0.35
