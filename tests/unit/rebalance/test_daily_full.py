from pathlib import Path
import tradingagents.rebalance.daily_full as df
from tradingagents.dataflows.universe import Universe, ETFEntry


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="x", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A357870", name="y", aum_krw=1e11, underlying_index="y",
                 bucket="안전", category="금리연계형/초단기채권")])


def _common(monkeypatch):
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 50, "A357870": 50}, 0,
                                   {"A069500": 0.5, "A357870": 0.5}))


def test_none_tier_no_trades(tmp_path, monkeypatch):
    _common(monkeypatch)
    monkeypatch.setattr(df, "_eval_triggers", lambda **k: ("none", {}, False))
    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert res.tier == "none"
    assert res.plan == []


def test_drift_rebalance_restores_prev_target(tmp_path, monkeypatch):
    _common(monkeypatch)
    # current drifted to A069500 0.6/A357870 0.4 vs prev_target 0.5/0.5
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 60, "A357870": 40}, 0,
                                   {"A069500": 0.5, "A357870": 0.5}))
    monkeypatch.setattr(df, "_eval_triggers", lambda **k: ("drift:rebalance", {"fired": ["drift:rebalance"]}, False))
    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert res.tier == "drift:rebalance"
    assert (tmp_path / "2026-06-08(rebalancing)_plan.csv").exists()
    # target restored to prev_target → A069500 should SELL (60→~50)
    assert any(tl.ticker == "A069500" and tl.action == "SELL" for tl in res.plan)
