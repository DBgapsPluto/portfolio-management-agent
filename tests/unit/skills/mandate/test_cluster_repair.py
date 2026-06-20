from tradingagents.schemas.technical import Cluster
from tradingagents.skills.mandate.cluster_repair import repair_cluster_cap, CLUSTER_CAP


def _cl(members):
    return Cluster(cluster_id="1", members=members, avg_internal_correlation=0.8,
                   category_label="semi")


def test_cluster_over_cap_scaled_down_degenerate_infeasible():
    # Degenerate fixture: non-cluster C=0.30 is already > SINGLE_CAP (0.20) on input,
    # and the only other non-cluster (CASH) is already AT 0.20, so there is zero room to
    # water-fill the freed mass under SINGLE_CAP. {cluster≤cap, single≤cap, 합=1} is
    # structurally infeasible. The repair falls back to a full renormalize (matching
    # repair_risk_cap's documented degenerate fallback), which re-inflates the cluster
    # slightly above cap — acceptable ONLY because no feasible solution exists. (The old
    # code instead silently emitted C=0.39, a single ETF far above the 20% hard cap.)
    w = {"A": 0.25, "B": 0.25, "C": 0.30, "CASH": 0.20}   # A+B=0.50 > 0.35
    out = repair_cluster_cap(w, [_cl(["A", "B"])], cap=0.35)
    assert abs(sum(out.values()) - 1.0) < 1e-6                         # sum=1 always preserved
    # cluster cap cannot be enforced without violating single cap (and vice-versa) here.


def test_cluster_over_cap_scaled_down():
    # Feasible analogue: cluster {A,B} over cap, with enough non-cluster headroom
    # (C1..C4 each < SINGLE_CAP) to water-fill the freed mass legally.
    w = {"A": 0.25, "B": 0.25, "C1": 0.125, "C2": 0.125, "C3": 0.125, "C4": 0.125}  # A+B=0.50 > 0.35
    out = repair_cluster_cap(w, [_cl(["A", "B"])], cap=0.35)
    assert sum(out[t] for t in ("A", "B")) <= 0.35 + 1e-6              # cluster cap
    assert abs(sum(out.values()) - 1.0) < 1e-6                         # sum=1
    assert all(v <= 0.20 + 1e-6 for v in out.values())                # single cap (the fix)


def test_cluster_repair_respects_single_cap_when_feasible():
    # cluster {A,B,C,D} over cap; uneven non-cluster (W large) so the water-fill
    # saturates some recipients and leftover mass remains. The buggy renormalize
    # dumped it proportionally → W=0.233 (>0.20). Non-cluster headroom
    # (4*0.20-0.40=0.40) ≥ freed (0.25), so {cluster≤cap, single≤cap, 합=1} is feasible.
    w = {"A": 0.20, "B": 0.20, "C": 0.10, "D": 0.10,
         "W": 0.18, "X": 0.10, "Y": 0.06, "Z": 0.06}
    out = repair_cluster_cap(w, [_cl(["A", "B", "C", "D"])], cap=0.35)
    assert sum(out[t] for t in ("A", "B", "C", "D")) <= 0.35 + 1e-6   # cluster cap
    assert abs(sum(out.values()) - 1.0) < 1e-6                        # sum=1
    assert all(v <= 0.20 + 1e-6 for v in out.values())               # single cap (the fix)


def test_cluster_under_cap_noop():
    w = {"A": 0.15, "B": 0.15, "CASH": 0.70}
    out = repair_cluster_cap(w, [_cl(["A", "B"])], cap=0.35)
    assert out == w


def test_default_cluster_cap_is_035():
    assert CLUSTER_CAP == 0.35
