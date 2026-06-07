from tradingagents.rebalance.overlay import defensive_overlay, risk_on_overlay


def test_defensive_reduces_risk_to_target():
    w = {"R": 0.65, "S": 0.35}
    out = defensive_overlay(w, is_risk=lambda t: t == "R", defensive_target=0.55)
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert out["R"] <= 0.55 + 1e-6
    assert out["S"] > 0.35


def test_defensive_noop_when_already_below():
    w = {"R": 0.40, "S": 0.60}
    out = defensive_overlay(w, is_risk=lambda t: t == "R", defensive_target=0.55)
    assert abs(out["R"] - 0.40) < 1e-9      # 이미 target 이하 → 변화 없음 (repair_risk_cap 동작)


def test_risk_on_increases_risk_within_cap():
    w = {"R": 0.50, "S": 0.50}
    out = risk_on_overlay(w, is_risk=lambda t: t == "R", step=0.05, hard_cap=0.70)
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert 0.50 < out["R"] <= 0.70 + 1e-6


def test_risk_on_clamped_at_hard_cap():
    w = {"R": 0.68, "S": 0.32}
    out = risk_on_overlay(w, is_risk=lambda t: t == "R", step=0.10, hard_cap=0.70)
    assert out["R"] <= 0.70 + 1e-6          # cap 초과 안 함
