import pytest
from tradingagents.skills.mandate.risk_repair import repair_risk_cap


def test_no_change_when_under_cap():
    w = {"r1": 0.30, "r2": 0.20, "s1": 0.30, "s2": 0.20}  # risk=0.50 ≤0.70
    out = repair_risk_cap(w, lambda t: t.startswith("r"))
    assert out == pytest.approx(w)


def test_scales_risk_to_cap_and_water_fills_safe():
    # risk=0.75>0.70; 안전 3개 → freed 0.05 흡수, 단일≤0.20 유지
    w = {"r1": 0.20, "r2": 0.20, "r3": 0.20, "r4": 0.15,
         "s1": 0.10, "s2": 0.10, "s3": 0.05}  # sum=1.0
    out = repair_risk_cap(w, lambda t: t.startswith("r"))
    assert sum(out[t] for t in ("r1", "r2", "r3", "r4")) == pytest.approx(0.70, abs=1e-6)
    assert sum(out[t] for t in ("s1", "s2", "s3")) == pytest.approx(0.30, abs=1e-6)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(x <= 0.20 + 1e-9 for x in out.values())
    # 위험 포지션 비례 축소(상대비 보존)
    assert out["r1"] / out["r4"] == pytest.approx(0.20 / 0.15)


def test_preserves_safe_relative_proportions():
    w = {"r1": 0.20, "r2": 0.20, "r3": 0.20, "r4": 0.15,
         "s1": 0.10, "s2": 0.10, "s3": 0.05}
    out = repair_risk_cap(w, lambda t: t.startswith("r"))
    # 안전은 비례 증가 → s1/s3 비율 보존 (water-fill 가 단일캡에 안 걸리는 범위)
    assert out["s1"] / out["s3"] == pytest.approx(0.10 / 0.05, rel=1e-3)


def test_empty_returns_empty():
    assert repair_risk_cap({}, lambda t: True) == {}


def test_all_risk_at_cap_boundary_no_change():
    w = {"r1": 0.20, "r2": 0.20, "r3": 0.20, "r4": 0.10, "s1": 0.30}  # risk=0.70 exactly
    assert repair_risk_cap(w, lambda t: t.startswith("r")) == pytest.approx(w)


def test_water_fill_no_silent_loss_on_uneven_headroom():
    # 리뷰 회귀(overlay.py 33ba11d 패턴 미러): 안전자산 헤드룸이 비중에 비례하지 않으면
    # (s1=0.19 는 room 0.01 뿐인데 비중 기준 분배 delta 는 0.038 로 room 을 넘겨 잘린다)
    # 옛 코드는 add -= give(의도한 분배량)로 차감해 그 잘림분(0.028)을 다음 반복으로 넘기지
    # 않고 통째로 유실시켰다. 유실분은 마지막 renormalize 가 위험자산까지 포함해 전량에
    # 되돌려 risk cap(0.70)과 single cap(0.20) 을 모두 재위반한다(고치기 전엔 r1=0.7202,
    # s1=0.2058 로 관측됨).
    w = {"r1": 0.75, "s1": 0.19, "s2": 0.01, "s3": 0.05}  # sum=1.0
    out = repair_risk_cap(w, lambda t: t == "r1")
    assert out["r1"] <= 0.70 + 1e-6                                    # risk cap 재위반 없음
    assert all(out[t] <= 0.20 + 1e-6 for t in ("s1", "s2", "s3"))      # single cap 재위반 없음
    safe_sum = out["s1"] + out["s2"] + out["s3"]
    assert abs(safe_sum - 0.30) < 1e-6                                 # freed 전량이 안전자산에 (유실 없음)
    assert abs(sum(out.values()) - 1.0) < 1e-9                         # 잔여가 나중 반복에서 s2/s3 로 도달
