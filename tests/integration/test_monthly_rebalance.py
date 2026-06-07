from pathlib import Path
import tradingagents.rebalance.monthly_full as mf
from tradingagents.schemas.portfolio import WeightVector, OptimizationMethod
from tradingagents.dataflows.universe import Universe, ETFEntry


def _uni():
    etfs = []
    for t in ["A069500", "A229200", "A233740"]:
        etfs.append(ETFEntry(ticker=t, name=t, aum_krw=1e12,
                    underlying_index="x", bucket="위험", category="국내주식_지수"))
    for t in ["A357870", "A357880", "A357890", "A357900"]:
        etfs.append(ETFEntry(ticker=t, name=t, aum_krw=1e11,
                    underlying_index="x", bucket="안전", category="금리연계형/초단기채권"))
    return Universe(version="t", etfs=etfs)


def test_monthly_full_produces_rebalance_artifacts(tmp_path, monkeypatch):
    prev = tmp_path / "2026-05-29"; prev.mkdir()
    (prev / "trade_plan.csv").write_text(
        "티커,수량(주)\nA069500,100\n", encoding="utf-8-sig")
    (prev / "portfolio.json").write_text(
        '{"as_of_date":"2026-05-29","weights":{"A069500":1.0},"correlation_clusters":[]}',
        encoding="utf-8")
    out_root = tmp_path / "artifacts"; out_root.mkdir()

    target_wv = WeightVector(method=OptimizationMethod.AUM_WEIGHTED,
        weights={"A069500": 0.15, "A229200": 0.15, "A357870": 0.18,
                 "A357880": 0.18, "A357890": 0.18, "A357900": 0.16}, rationale="t")

    class _Graph:
        def run(self, as_of_date, capital_krw, previous_portfolio=None):
            assert previous_portfolio is not None      # gap #1: must be forwarded
            return {"final_portfolio_path": str(out_root / "2026-06-30" / "portfolio.json"),
                    "weight_vector": target_wv,
                    "universe_path": "data/universe.json",
                    "correlation_clusters": []}

    monkeypatch.setattr(mf, "TradingAgentsGraph", lambda *a, **k: _Graph())
    monkeypatch.setattr(mf, "fetch_current_prices",
                        lambda d: {t: 10000.0 for t in
                                   ["A069500","A229200","A233740","A357870","A357880","A357890","A357900"]})
    monkeypatch.setattr(mf, "load_universe", lambda p: _uni())
    # artifacts_dir → tmp
    monkeypatch.setattr(mf, "DEFAULT_CONFIG", {**mf.DEFAULT_CONFIG, "artifacts_dir": str(out_root)})
    # avoid real LLM for rationale
    monkeypatch.setattr(mf, "_build_deep_llm", lambda: None, raising=False)

    res = mf.run(month=7, as_of="2026-06-30", previous_path=str(prev))
    assert Path(res.rebalance_paths["plan_csv"]).exists()
    assert Path(res.rebalance_paths["json"]).exists()
    assert Path(res.rebalance_paths["rationale_md"]).exists()
