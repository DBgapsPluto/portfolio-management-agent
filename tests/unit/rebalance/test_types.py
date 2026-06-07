from tradingagents.rebalance.types import TradeLine, RebalanceResult


def test_trade_line_fields():
    t = TradeLine(ticker="A069500", action="BUY", current_qty=0,
                  target_qty=10, delta_qty=10, delta_amount_krw=100000)
    assert t.action == "BUY"
    assert t.delta_qty == 10


def test_rebalance_result_defaults():
    r = RebalanceResult(as_of="2026-06-07", tier="monthly")
    assert r.plan == []
    assert r.cash_residual_krw == 0
    assert r.tier == "monthly"
