from tradingagents.rebalance.triggers import evaluate_drift, route_tier


def _dials():
    return dict(single_etf_abs_cap=0.19, single_etf_rel_band=0.05, risk_asset_abs_cap=0.68)


def test_drift_single_abs():
    fired = evaluate_drift({"A": 0.20}, {"A": 0.15}, _dials(), is_risk=lambda t: False)
    assert "drift:rebalance" in fired      # 0.20 > 0.19


def test_drift_rel_band():
    fired = evaluate_drift({"A": 0.10, "B": 0.90}, {"A": 0.16, "B": 0.84}, _dials(),
                           is_risk=lambda t: False)
    assert "drift:rebalance" in fired      # |0.10-0.16|=0.06 > 0.05


def test_drift_risk_defensive():
    fired = evaluate_drift({"R": 0.69, "S": 0.31}, {"R": 0.60, "S": 0.40}, _dials(),
                           is_risk=lambda t: t == "R")
    assert "drift:defensive" in fired      # 위험합 0.69 > 0.68


def test_drift_none_when_within_bands():
    fired = evaluate_drift({"A": 0.15, "B": 0.85}, {"A": 0.15, "B": 0.85}, _dials(),
                           is_risk=lambda t: False)
    assert fired == []


def test_route_priority_emergency_beats_drift():
    tier = route_tier(event_action="emergency_defensive_proposal",
                      drift_fired=["drift:rebalance"], reassess_fired=False)
    assert tier == "event:emergency_defensive"


def test_route_none_when_nothing():
    assert route_tier(event_action=None, drift_fired=[], reassess_fired=False) == "none"


def test_route_reassess_above_drift():
    tier = route_tier(event_action=None, drift_fired=["drift:rebalance"], reassess_fired=True)
    assert tier == "reassess"


def test_route_defensive_above_rebalance():
    tier = route_tier(event_action=None, drift_fired=["drift:rebalance", "drift:defensive"],
                      reassess_fired=False)
    assert tier == "drift:defensive"
