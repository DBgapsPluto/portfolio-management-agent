from tradingagents.rebalance.engine import build_rebalance_plan


def _dials():
    return dict(no_trade_band=0.005, single_etf_abs_cap=0.19,
                risk_asset_abs_cap=0.68)


def test_buy_sell_hold_classification():
    current = {"A": 0.50, "B": 0.50}
    target = {"A": 0.30, "B": 0.70}
    prices = {"A": 10000.0, "B": 10000.0}
    res = build_rebalance_plan(current, target, capital=1_000_000,
                               prices=prices, is_risk=lambda t: False, dials=_dials())
    by = {tl.ticker: tl for tl in res["plan"]}
    assert by["A"].action == "SELL" and by["A"].delta_qty < 0
    assert by["B"].action == "BUY" and by["B"].delta_qty > 0


def test_cash_residual_held_not_swept():
    # 목표 100% A지만 정수 qty 반올림으로 잔여 발생 → 현금 보유.
    current = {"A": 0.0}
    target = {"A": 1.0}
    prices = {"A": 30000.0}          # 1,000,000 / 30,000 = 33.33 → 33주 = 990,000
    res = build_rebalance_plan(current, target, capital=1_000_000,
                               prices=prices, is_risk=lambda t: False, dials=_dials())
    assert res["cash_residual_krw"] == 10000     # 1,000,000 - 33*30,000
    assert res["realized_weights"]["CASH"] == 0.01
    # 현금성 ETF 추가 매수 라인이 없어야(sweep 안 함)
    assert all(tl.ticker == "A" for tl in res["plan"])


def test_turnover_realized():
    current = {"A": 0.50, "B": 0.50}
    target = {"A": 0.30, "B": 0.70}
    prices = {"A": 10000.0, "B": 10000.0}
    res = build_rebalance_plan(current, target, capital=1_000_000,
                               prices=prices, is_risk=lambda t: False, dials=_dials())
    # 매도 A ~0.20, 매수 B ~0.20 → turnover ≈ (0.20+0.20) = 0.40 (정수 반올림 오차 허용)
    assert abs(res["turnover"] - 0.40) < 0.02
