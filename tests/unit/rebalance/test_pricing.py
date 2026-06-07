from datetime import date
import tradingagents.rebalance.pricing as pricing


def test_walks_back_when_today_empty(monkeypatch):
    calls = []
    def fake_close_map(d):
        calls.append(d)
        return {"A069500": 10000.0} if d == date(2026, 6, 5) else {}
    monkeypatch.setattr(pricing, "fetch_etf_close_map", fake_close_map, raising=False)
    out = pricing.fetch_current_prices(date(2026, 6, 7))
    assert out == {"A069500": 10000.0}
    assert calls[0] == date(2026, 6, 7)   # 오늘부터 시작
    assert date(2026, 6, 5) in calls       # walk-back 도달


def test_empty_on_total_failure(monkeypatch):
    monkeypatch.setattr(pricing, "fetch_etf_close_map", lambda d: {}, raising=False)
    assert pricing.fetch_current_prices(date(2026, 6, 7)) == {}
