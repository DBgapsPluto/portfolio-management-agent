from tradingagents.rebalance.overlay import defensive_overlay, risk_on_overlay


def test_defensive_reduces_risk_to_target():
    # 안전자산을 single-cap(0.20) 헤드룸이 넉넉한 3종으로 분산 — water-fill 이 단일-cap
    # 포화 없이 순수 risk/safe 재배분만 검증하도록.
    w = {"R": 0.65, "S1": 0.15, "S2": 0.10, "S3": 0.10}
    out = defensive_overlay(w, is_risk=lambda t: t == "R", defensive_target=0.55)
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert out["R"] <= 0.55 + 1e-6
    assert (out["S1"] + out["S2"] + out["S3"]) > 0.35


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


# --- F1: 위기 전용 sell_ok/dest_ok (crisis_policy 배선) ---------------------------------

def test_defensive_protects_sell_ok_false_risk_asset():
    # GOLD 는 위험자산(is_risk)이지만 crisis_policy 상 sell_ok=False(도피처 보호) — 비례 축소
    # 대상에서 빠지고 원 비중을 그대로 유지해야 한다(F1 오버레이 방향).
    w = {"EQ": 0.40, "GOLD": 0.10, "SAFE1": 0.20, "SAFE2": 0.20, "SAFE3": 0.10}
    out = defensive_overlay(w, is_risk=lambda t: t in ("EQ", "GOLD"),
                            defensive_target=0.30,
                            sell_ok=lambda t: t != "GOLD", dest_ok=lambda t: True)
    assert abs(out["GOLD"] - 0.10) < 1e-9   # 보호 — 스케일 안 됨
    assert out["EQ"] < 0.40                 # 매도 가능 위험만 축소
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_defensive_excludes_dest_ok_false_from_water_fill():
    # HY 는 안전자산(not is_risk)이지만 crisis_policy 상 dest_ok=False(하이일드 크레딧) —
    # 물채움 대상에서 제외되고 원 비중을 그대로 유지해야 한다(F1 오버레이 방향).
    w = {"EQ": 0.60, "HY": 0.10, "SAFE1": 0.15, "SAFE2": 0.15}
    out = defensive_overlay(w, is_risk=lambda t: t == "EQ", defensive_target=0.40,
                            sell_ok=lambda t: True, dest_ok=lambda t: t != "HY")
    assert abs(out["HY"] - 0.10) < 1e-9     # 목적지 제외 — 물채움 안 받음
    assert (out["SAFE1"] + out["SAFE2"]) > 0.30   # 물채움은 dest_ok 안전자산으로만
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_cash_is_last_resort_destination():
    # 목적지 ETF들이 single-cap(0.20)에 포화되면 잔여는 CASH로 (감사 MF-10).
    w = {"EQ1": 0.60, "KTB1": 0.19, "TIPS1": 0.19, "CASH": 0.02}
    out = defensive_overlay(w, is_risk=lambda t: t == "EQ1", defensive_target=0.40,
                            sell_ok=lambda t: True, dest_ok=lambda t: True)
    assert out["CASH"] > 0.02 + 1e-9        # 포화 초과분이 현금으로
    assert max(out["KTB1"], out["TIPS1"]) <= 0.20 + 1e-9
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_defensive_cuts_protected_when_alone_over_target():
    # 2단계 가드(라이브 도달 희박, CATEGORY_CAPS[FX 및 원자재]=0.20 이 선행 제한): 보호자산
    # 만으로 이미 defensive_target 을 넘으면 매도-가능 자산을 0까지 팔고도 부족하므로 보호자산도
    # 비례 컷한다. crash 하지 않고 target 근처로 수렴해야 한다.
    w = {"EQ": 0.10, "GOLD": 0.50, "SAFE": 0.40}
    out = defensive_overlay(w, is_risk=lambda t: t in ("EQ", "GOLD"), defensive_target=0.30,
                            sell_ok=lambda t: t != "GOLD", dest_ok=lambda t: True)
    assert out["GOLD"] < 0.50               # 가드 경로 — 보호자산도 컷
    risk_after = out["EQ"] + out["GOLD"]
    assert risk_after <= 0.30 + 1e-6
    assert abs(sum(out.values()) - 1.0) < 1e-9
