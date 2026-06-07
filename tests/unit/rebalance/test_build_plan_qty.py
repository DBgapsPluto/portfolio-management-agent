from tradingagents.rebalance.engine import build_rebalance_plan


def _dials():
    return dict(no_trade_band=0.005, single_etf_abs_cap=0.19,
                risk_asset_abs_cap=0.68)


def test_buy_sell_hold_classification():
    # 큰 보유(A,B 각 50%) → 분산 목표(각 ≤0.20). A 축소(SELL), 신규 C 매수(BUY).
    current = {"A": 0.5, "B": 0.5}
    target = {"A": 0.1, "B": 0.1, "C": 0.2, "D": 0.2, "E": 0.2, "F": 0.2}
    prices = {t: 10000.0 for t in "ABCDEF"}
    res = build_rebalance_plan(current, target, prev_qty={"A": 50, "B": 50},
                               current_value=1_000_000, prices=prices,
                               is_risk=lambda t: False, dials=_dials())
    by = {tl.ticker: tl for tl in res["plan"]}
    assert by["A"].action == "SELL" and by["A"].delta_qty < 0
    assert by["C"].action == "BUY" and by["C"].delta_qty > 0
    # 단일 cap 준수: 어떤 종목도 realized 20% 초과 불가
    assert max(res["realized_weights"].get(t, 0) for t in "ABCDEF") <= 0.20 + 1e-9


def test_current_qty_is_real_qty_under_price_drift():
    # BUG 1: V ≠ naive capital. prev_qty=50 @ 21,000 → V=1,050,000.
    # 잘못된 capital(1,000,000) 기반이면 round(1,000,000/21,000)=48 이 됨.
    # current_qty 필드는 prev_qty 를 그대로 반영해야 한다(capital 역산 아님).
    current = {"A": 0.2, "B": 0.2, "C": 0.2, "D": 0.2, "E": 0.2}
    target = {"A": 0.2, "B": 0.2, "C": 0.2, "D": 0.2, "E": 0.2}
    prev_qty = {"A": 50, "B": 10, "C": 10, "D": 10, "E": 10}
    prices = {"A": 21000.0, "B": 21000.0, "C": 21000.0, "D": 21000.0, "E": 21000.0}
    # current_value = 50*21000 + 10*21000*4 = 1,050,000 + 840,000 = 1,890,000
    current_value = 1_890_000
    res = build_rebalance_plan(current, target, prev_qty=prev_qty,
                               current_value=current_value, prices=prices,
                               is_risk=lambda t: False, dials=_dials())
    by = {tl.ticker: tl for tl in res["plan"]}
    # A의 current_qty 는 prev_qty["A"]=50, NOT capital-based round(1_890_000/21_000)=90
    assert by["A"].current_qty == 50
    # cap_qty = int(0.20 * 1_890_000 / 21_000) = int(18.0) = 18
    # tgt_qty = min(round(0.20*1_890_000/21_000), 18) = min(18, 18) = 18 → SELL (50→18)
    assert by["A"].target_qty == 18
    assert by["A"].action == "SELL"


def test_cash_residual_held_not_swept():
    # 목표가 종목 합 0.9(나머지 0.1은 의도적 현금) → 잔여 현금 보유, 종목 매수만.
    current = {"A": 0.0}
    target = {"A": 0.2, "B": 0.2, "C": 0.2, "D": 0.2, "E": 0.1}  # 합 0.9
    prices = {t: 10000.0 for t in "ABCDE"}
    res = build_rebalance_plan(current, target, prev_qty={}, current_value=1_000_000,
                               prices=prices, is_risk=lambda t: False, dials=_dials())
    assert res["cash_residual_krw"] > 0           # 현금 잔여 보유
    assert res["realized_weights"].get("CASH", 0) > 0
    assert all(tl.action in ("BUY", "HOLD") for tl in res["plan"])   # 신규 매수, sweep 없음


def test_turnover_realized():
    current = {"A": 0.5, "B": 0.5}
    target = {"A": 0.1, "B": 0.1, "C": 0.2, "D": 0.2, "E": 0.2, "F": 0.2}
    prices = {t: 10000.0 for t in "ABCDEF"}
    res = build_rebalance_plan(current, target, prev_qty={"A": 50, "B": 50},
                               current_value=1_000_000, prices=prices,
                               is_risk=lambda t: False, dials=_dials())
    assert res["turnover"] > 0.0
