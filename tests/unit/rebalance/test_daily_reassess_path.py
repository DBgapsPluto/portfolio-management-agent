import tradingagents.rebalance.daily_full as df
from tradingagents.dataflows.universe import Universe, ETFEntry


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="x", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A357870", name="y", aum_krw=1e11, underlying_index="y",
                 bucket="안전", category="금리연계형/초단기채권")])


def test_reassess_tier_fires_and_produces_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "_load_prev",
                        lambda p: ({"A069500": 60, "A357870": 40}, 0,
                                   {"A069500": 0.6, "A357870": 0.4}))
    # daily_triggers.run → context triggers reassess (yield curve), no event/drift
    class _Trig:
        fired = []; suggested_action = None
        context = {"spread_10y_2y_bps": -60, "vix": 20, "vix_change_5d": 0.0,
                   "any_etf_weight": 0.6}
    monkeypatch.setattr(df.daily_triggers, "run", lambda **k: _Trig())
    # weekly_tilt (reassess engine) → regime changed, risk down
    import tradingagents.rebalance.reassess as ra
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": -0.05}})())
    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert res.tier == "reassess"
    assert (tmp_path / "2026-06-08(rebalancing)_plan.csv").exists()
