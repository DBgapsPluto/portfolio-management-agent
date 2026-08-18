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


def test_reassess_de_risk_protects_sell_ok_false_bucket(monkeypatch):
    # F1/B3(MF-9): 위기 보호 자산(sell_ok=False, 예: GOLD)은 reassess 축소 경로에서도
    # rf 스케일 대상에서 제외 — 원 비중 그대로 유지해야 한다.
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": -0.20}})())
    out = ra.reassess_target(
        {"EQ": 0.50, "GOLD": 0.20, "SAFE": 0.30},
        is_risk=lambda t: t in ("EQ", "GOLD"),
        as_of="2026-06-08", previous_path=None,
        sell_ok=lambda t: t != "GOLD",
    )
    assert abs(out["GOLD"] - 0.20) < 1e-9   # 보호 — 스케일 안 됨(정확히 원 비중)
    assert out["EQ"] < 0.50                 # 매도 가능 위험만 축소
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_reassess_risk_on_does_not_freeze_protected_bucket(monkeypatch):
    # 리뷰 must_fix #2: sell_ok 는 "팔아도 되는가" — risk 확대(risk-ON, delta>0)는 매도가
    # 아니므로 보호를 적용하면 안 된다. 위험자산 전량이 보호 버킷뿐인 book 에서 risk-ON 이
    # scalable_sum<=0 으로 통째 None 이 되면 안 된다.
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": 0.10}})())
    out = ra.reassess_target(
        {"GOLD": 0.30, "SAFE": 0.70},
        is_risk=lambda t: t == "GOLD",
        as_of="2026-06-08", previous_path=None,
        sell_ok=lambda t: t != "GOLD",
    )
    assert out is not None
    assert out["GOLD"] > 0.30


def test_reassess_risk_on_scales_protected_bucket_too(monkeypatch):
    # 혼합 book: 보호 자산이 확대에서 배제되면 전량이 매도-가능 위험자산에만 쏠린다(리뷰
    # 실측: GOLD 0.20 고정·EQ 0.30) — risk-ON 은 GOLD 도 EQ 와 동일 비율로 늘어야 한다.
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": 0.10}})())
    out = ra.reassess_target(
        {"GOLD": 0.20, "EQ": 0.20, "SAFE": 0.60},
        is_risk=lambda t: t in ("GOLD", "EQ"),
        as_of="2026-06-08", previous_path=None,
        sell_ok=lambda t: t != "GOLD",
    )
    assert out["GOLD"] > 0.20
    assert abs(out["GOLD"] - out["EQ"]) < 1e-9   # 동일 출발 비중 → 비례 동일 증가


def test_reassess_sell_ok_default_matches_prior_behavior(monkeypatch):
    # sell_ok 미전달 시 기존(전량 스케일) 동작과 동치 — 하위 호환.
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": -0.05}})())
    out = ra.reassess_target({"R": 0.60, "S": 0.40}, is_risk=lambda t: t == "R",
                             as_of="2026-06-08", previous_path=None)
    assert abs(out["R"] - 0.55) < 1e-9
    assert abs(out["S"] - 0.45) < 1e-9
