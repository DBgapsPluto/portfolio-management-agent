from tradingagents.rebalance.engine import build_rebalance_plan


def _dials():
    return dict(no_trade_band=0.005, single_etf_abs_cap=0.19,
                risk_asset_abs_cap=0.68)


def test_buy_sell_hold_classification():
    current = {"A": 0.50, "B": 0.50}
    target = {"A": 0.30, "B": 0.70}
    prev_qty = {"A": 50, "B": 50}
    prices = {"A": 10000.0, "B": 10000.0}
    res = build_rebalance_plan(current, target, prev_qty=prev_qty,
                               current_value=1_000_000, prices=prices,
                               is_risk=lambda t: False, dials=_dials())
    by = {tl.ticker: tl for tl in res["plan"]}
    # 실제 보유수량 기준: A 50 → 30(SELL, dq -20), B 50 → 70(BUY, dq +20)
    assert by["A"].action == "SELL"
    assert by["A"].current_qty == 50 and by["A"].target_qty == 30 and by["A"].delta_qty == -20
    assert by["B"].action == "BUY"
    assert by["B"].current_qty == 50 and by["B"].target_qty == 70 and by["B"].delta_qty == 20


def test_current_qty_is_real_qty_under_price_drift():
    # BUG 1: V ≠ naive capital. prev_qty=50 @ 21,000 → V=1,050,000.
    # 잘못된 capital(1,000,000) 기반이면 round(1,000,000/21,000)=48 이 됨.
    # 실제 보유수량 50 이 그대로 나와야 한다.
    current = {"A": 1.0}
    target = {"A": 1.0}
    prev_qty = {"A": 50}
    prices = {"A": 21000.0}
    res = build_rebalance_plan(current, target, prev_qty=prev_qty,
                               current_value=1_050_000, prices=prices,
                               is_risk=lambda t: False, dials=_dials())
    a = res["plan"][0]
    assert a.ticker == "A"
    assert a.current_qty == 50          # REAL qty, NOT capital-based 48
    assert a.target_qty == 50           # round(1.0*1,050,000/21,000)=50
    assert a.delta_qty == 0 and a.action == "HOLD"


def test_cash_residual_held_not_swept():
    # 목표 100% A지만 정수 qty 반올림으로 잔여 발생 → 현금 보유.
    current = {"A": 0.0}
    target = {"A": 1.0}
    prev_qty = {"A": 0}
    prices = {"A": 30000.0}          # 1,000,000 / 30,000 = 33.33 → 33주 = 990,000
    res = build_rebalance_plan(current, target, prev_qty=prev_qty,
                               current_value=1_000_000, prices=prices,
                               is_risk=lambda t: False, dials=_dials())
    assert res["cash_residual_krw"] == 10000     # 1,000,000 - 33*30,000
    assert res["realized_weights"]["CASH"] == 0.01
    # 현금성 ETF 추가 매수 라인이 없어야(sweep 안 함)
    assert all(tl.ticker == "A" for tl in res["plan"])


def test_turnover_realized():
    current = {"A": 0.50, "B": 0.50}
    target = {"A": 0.30, "B": 0.70}
    prev_qty = {"A": 50, "B": 50}
    prices = {"A": 10000.0, "B": 10000.0}
    res = build_rebalance_plan(current, target, prev_qty=prev_qty,
                               current_value=1_000_000, prices=prices,
                               is_risk=lambda t: False, dials=_dials())
    # 매도 A ~0.20, 매수 B ~0.20 → turnover ≈ (0.20+0.20) = 0.40 (정수 반올림 오차 허용)
    assert abs(res["turnover"] - 0.40) < 0.02
