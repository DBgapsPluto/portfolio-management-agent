"""Unit tests for monthly_full pipeline (TradingAgentsGraph mocked)."""
from unittest.mock import MagicMock, patch
from pathlib import Path

from tradingagents.schemas.portfolio import WeightVector, OptimizationMethod
from tradingagents.dataflows.universe import Universe, ETFEntry


def _mini_uni():
    etfs = [
        ETFEntry(ticker="A069500", name="KODEX 200", aum_krw=1e12,
                 underlying_index="KOSPI 200", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A357870", name="KODEX 단기채권", aum_krw=1e11,
                 underlying_index="KAP단기채권", bucket="안전", category="금리연계형/초단기채권"),
    ]
    return Universe(version="t", etfs=etfs)


def _make_graph_mock(tmp_path):
    wv = WeightVector(method=OptimizationMethod.AUM_WEIGHTED,
                      weights={"A069500": 0.6, "A357870": 0.4}, rationale="t")
    out_dir = tmp_path / "2026-06-30"
    out_dir.mkdir(parents=True, exist_ok=True)
    mock = MagicMock()
    mock.run.return_value = {
        "final_portfolio_path": str(out_dir / "portfolio.json"),
        "weight_vector": wv,
        "universe_path": "data/universe.json",
        "correlation_clusters": [],
    }
    return mock


def test_monthly_run_returns_result(monkeypatch, tmp_path):
    from tradingagents.rebalance import monthly_full as mf

    fake_graph = _make_graph_mock(tmp_path)
    monkeypatch.setattr(mf, "TradingAgentsGraph", lambda *a, **k: fake_graph)
    monkeypatch.setattr(mf, "load_universe", lambda p: _mini_uni())
    monkeypatch.setattr(mf, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(mf, "DEFAULT_CONFIG",
                        {**mf.DEFAULT_CONFIG, "artifacts_dir": str(tmp_path)})
    monkeypatch.setattr(mf, "_build_deep_llm", lambda: None)

    result = mf.run(month=6, as_of="2026-06-30")
    assert result.portfolio_path == str(tmp_path / "2026-06-30" / "portfolio.json")
    assert "plan_csv" in result.rebalance_paths
    assert "Month 6" in result.summary
    fake_graph.run.assert_called_once()
    assert fake_graph.run.call_args.kwargs["as_of_date"] == "2026-06-30"


def test_monthly_run_uses_default_capital(monkeypatch, tmp_path):
    from tradingagents.rebalance import monthly_full as mf

    fake_graph = _make_graph_mock(tmp_path)
    monkeypatch.setattr(mf, "TradingAgentsGraph", lambda *a, **k: fake_graph)
    monkeypatch.setattr(mf, "load_universe", lambda p: _mini_uni())
    monkeypatch.setattr(mf, "fetch_current_prices",
                        lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(mf, "DEFAULT_CONFIG",
                        {**mf.DEFAULT_CONFIG, "artifacts_dir": str(tmp_path)})
    monkeypatch.setattr(mf, "_build_deep_llm", lambda: None)

    mf.run(month=7, as_of="2026-07-31")
    capital = fake_graph.run.call_args.kwargs["capital_krw"]
    assert capital >= 100_000_000  # sane default
