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
