import tradingagents.rebalance.reassess as ra


def test_no_regime_change_returns_none(monkeypatch):
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": False, "tilt_proposed": {}})())
    out = ra.reassess_target({"R": 0.6, "S": 0.4}, is_risk=lambda t: t == "R",
                             as_of="2026-06-08", previous_path=None)
    assert out is None


def test_regime_change_tilts_risk_down(monkeypatch):
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": -0.05}})())
    out = ra.reassess_target({"R": 0.60, "S": 0.40}, is_risk=lambda t: t == "R",
                             as_of="2026-06-08", previous_path=None)
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert out["R"] < 0.60
    assert out["S"] > 0.40


def test_zero_delta_returns_none(monkeypatch):
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": 0.0}})())
    out = ra.reassess_target({"R": 0.6, "S": 0.4}, is_risk=lambda t: t == "R",
                             as_of="2026-06-08", previous_path=None)
    assert out is None


def test_cash_excluded_from_scaling(monkeypatch):
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": -0.05}})())
    out = ra.reassess_target({"R": 0.50, "S": 0.40, "CASH": 0.10},
                             is_risk=lambda t: t == "R", as_of="2026-06-08", previous_path=None)
    # CASH 는 스케일 대상 아님 → 결과에 종목만, 합 1.0
    assert "CASH" not in out
    assert abs(sum(out.values()) - 1.0) < 1e-9
