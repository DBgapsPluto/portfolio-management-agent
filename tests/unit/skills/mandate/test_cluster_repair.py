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


def test_cluster_water_fill_no_silent_loss_on_uneven_headroom():
    # 리뷰 회귀(overlay.py 33ba11d 패턴 미러): 첫 번째 클러스터 water-fill 루프(비-군집
    # 목적지 분배)가 헤드룸이 비중에 비례하지 않을 때(R1=0.15 는 room 0.05 뿐인데 비중 기준
    # delta 가 room 을 살짝 넘겨 잘린다) freed -= give(의도한 분배량)로 차감해 그 잘림분을
    # 유실시켰다. 이 손실(~3e-7)은 파일 자체의 FLOAT_TOLERANCE(1e-6)보다 작아 하단의
    # "sum=1 복구" 안전망조차 발동하지 않고 그대로 새 나간다 — 엄격한(1e-9) 보존 검사로만
    # 드러난다. 값은 손실이 정확히 1e-9~1e-6 구간에 오도록(안전망을 우회하도록) 역산됨.
    loss = 3e-7
    freed = (0.05 + loss) * 4 / 3          # R1 room(0.05) 을 loss 만큼 넘기는 give
    csum = 0.35 + freed
    w = {
        "A": 0.30, "B": csum - 0.30,       # cluster: 합 csum (cap=0.35 초과분 = freed)
        "R1": 0.15, "R2": 0.05,            # 비-군집 목적지: room 0.05 / 0.15 (불균등)
        "PAD": 1.0 - csum - 0.15 - 0.05,   # single-cap 이상 이미 포화 — 물채움 후보 아님
    }
    assert abs(sum(w.values()) - 1.0) < 1e-9
    out = repair_cluster_cap(w, [_cl(["A", "B"])], cap=0.35)
    assert sum(out[t] for t in ("A", "B")) <= 0.35 + 1e-6              # cluster cap
    assert out["R1"] <= 0.20 + 1e-9
    assert out["R2"] <= 0.20 + 1e-9
    assert abs(sum(out.values()) - 1.0) < 1e-9                         # 엄격 보존 — 유실 없음
    # R1 이 room(0.05) 만큼 정확히 포화되므로 freed 전량(R1 의 0.05 + R2 몫)은 R2 로 귀결—
    # 잘린 잔여(loss)가 다음 반복에서 아직 포화되지 않은 R2 로 도달했는지 확인.
    assert abs(out["R2"] - freed) < 1e-9
