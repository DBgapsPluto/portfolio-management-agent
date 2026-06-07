from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.rebalance.engine import run_rebalance


def _uni():
    etfs = []
    for t in ["A069500", "A229200", "A233740"]:            # kr_equity (RISK)
        etfs.append(ETFEntry(ticker=t, name=t, aum_krw=1e12,
                    underlying_index="x", bucket="위험", category="국내주식_지수"))
    for t in ["A357870", "A357880", "A357890", "A357900"]:  # cash_mmf (SAFE)
        etfs.append(ETFEntry(ticker=t, name=t, aum_krw=1e11,
                    underlying_index="x", bucket="안전", category="금리연계형/초단기채권"))
    return Universe(version="t", etfs=etfs)


def test_run_rebalance_end_to_end(tmp_path):
    out_dir = tmp_path / "2026-06-07"; out_dir.mkdir()
    prices = {t: 10000.0 for t in
              ["A069500", "A229200", "A233740", "A357870", "A357880", "A357890", "A357900"]}
    res = run_rebalance(
        as_of="2026-06-07", tier="monthly", capital=1_000_000,
        prev_qty={"A069500": 100}, prev_cash=0,
        target_weights={"A069500": 0.15, "A229200": 0.15, "A357870": 0.18,
                        "A357880": 0.18, "A357890": 0.18, "A357900": 0.16},
        prices=prices, universe=_uni(), clusters=[], previous_weights={"A069500": 1.0},
        dials=dict(no_trade_band=0.005, single_etf_abs_cap=0.19,
                   risk_asset_abs_cap=0.68, turnover_floor_monthly=0.10),
        out_dir=out_dir, previous_path="artifacts/2026-06-05", deep_llm=None,
    )
    assert res.tier == "monthly"
    assert res.validation.passed
    assert (out_dir / "2026-06-07(rebalancing).json").exists()
    assert (out_dir / "2026-06-07(rebalancing)_plan.csv").exists()
    assert (out_dir / "2026-06-07(rebalancing)_rationale.md").exists()
    # 현재 A069500 100% → 목표 0.15 → SELL 발생
    assert any(tl.ticker == "A069500" and tl.action == "SELL" for tl in res.plan)
