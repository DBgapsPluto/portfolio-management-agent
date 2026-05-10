from datetime import date
from tradingagents.skills.risk.breadth import compute_market_breadth


def test_breadth_stub_returns_snapshot():
    snap = compute_market_breadth("KOSPI200", date(2026, 5, 10))
    assert snap.market == "KOSPI200"
    assert 0 <= snap.advancing_pct <= 1
