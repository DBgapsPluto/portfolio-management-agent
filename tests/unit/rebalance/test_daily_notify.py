import tradingagents.rebalance.daily_full as df
from tradingagents.dataflows.universe import Universe, ETFEntry


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="x", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A357870", name="y", aum_krw=1e11, underlying_index="y",
                 bucket="안전", category="금리연계형/초단기채권")])


def _common(monkeypatch, calls):
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "send_rebalance_alert",
                        lambda *a, **k: calls.update(n=calls.get("n", 0) + 1) or True)


def test_alert_sent_on_trade(tmp_path, monkeypatch):
    calls = {}
    _common(monkeypatch, calls)
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 60, "A357870": 40}, 0,
                                   {"A069500": 0.5, "A357870": 0.5}))
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("drift:rebalance", {"fired": ["drift:rebalance"]}, False))
    df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert calls.get("n", 0) == 1


def test_no_alert_on_none_tier(tmp_path, monkeypatch):
    calls = {}
    _common(monkeypatch, calls)
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 50, "A357870": 50}, 0,
                                   {"A069500": 0.5, "A357870": 0.5}))
    monkeypatch.setattr(df, "_eval_triggers", lambda **k: ("none", {}, False))
    df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert calls.get("n", 0) == 0
