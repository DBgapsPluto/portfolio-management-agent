from tradingagents.rebalance.engine import reprice_holdings


def test_reprice_includes_cash_and_sums_to_one():
    qty = {"A069500": 50, "A229200": 25}
    prices = {"A069500": 10000.0, "A229200": 20000.0}
    # 평가액: 500000 + 500000 = 1,000,000, 현금 0
    w = reprice_holdings(qty, cash_krw=0, prices=prices)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w["A069500"] - 0.5) < 1e-9
    assert abs(w["A229200"] - 0.5) < 1e-9
    assert "CASH" not in w or w.get("CASH", 0) == 0


def test_reprice_cash_weight():
    qty = {"A069500": 50}
    prices = {"A069500": 10000.0}  # 평가액 500,000 + 현금 500,000 = 1,000,000
    w = reprice_holdings(qty, cash_krw=500000, prices=prices)
    assert abs(w["A069500"] - 0.5) < 1e-9
    assert abs(w["CASH"] - 0.5) < 1e-9


def test_reprice_missing_price_zero_weight():
    qty = {"A069500": 50, "AMISSING": 10}
    prices = {"A069500": 10000.0}  # AMISSING 가격 없음
    w = reprice_holdings(qty, cash_krw=0, prices=prices)
    assert w["A069500"] == 1.0          # 전체가 A069500
    assert w.get("AMISSING", 0.0) == 0.0
