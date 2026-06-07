from pathlib import Path
import tradingagents.rebalance.daily_full as df
from tradingagents.dataflows.universe import Universe, ETFEntry


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="x", aum_krw=1e12, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A357870", name="y", aum_krw=1e11, underlying_index="y",
                 bucket="안전", category="금리연계형/초단기채권")])


def test_daily_drift_produces_plan(tmp_path, monkeypatch):
    prev = tmp_path / "prev"; prev.mkdir()
    (prev / "portfolio.json").write_text(
        '{"weights":{"A069500":0.5,"A357870":0.5}}', encoding="utf-8")
    (prev / "trade_plan.csv").write_text(
        "티커,수량(주)\nA069500,60\nA357870,40\n", encoding="utf-8-sig")
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr(df, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "_eval_triggers",
                        lambda **k: ("drift:rebalance", {"fired": ["drift:rebalance"]}, False))
    res = df.run(as_of="2026-06-08", previous_path=str(prev), out_dir=out)
    assert res.tier == "drift:rebalance"
    assert (out / "2026-06-08(rebalancing)_plan.csv").exists()
    assert any(tl.ticker == "A069500" and tl.action == "SELL" for tl in res.plan)


def test_daily_none_tier_no_files(tmp_path, monkeypatch):
    prev = tmp_path / "prev"; prev.mkdir()
    (prev / "portfolio.json").write_text('{"weights":{"A069500":0.5,"A357870":0.5}}', encoding="utf-8")
    (prev / "trade_plan.csv").write_text("티커,수량(주)\nA069500,50\nA357870,50\n", encoding="utf-8-sig")
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr(df, "fetch_current_prices", lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "_eval_triggers", lambda **k: ("none", {}, False))
    res = df.run(as_of="2026-06-08", previous_path=str(prev), out_dir=out)
    assert res.tier == "none"
    assert not (out / "2026-06-08(rebalancing)_plan.csv").exists()
