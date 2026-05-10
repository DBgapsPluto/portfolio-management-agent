"""Unit tests for monthly_full pipeline (TradingAgentsGraph mocked)."""
from unittest.mock import MagicMock


def test_monthly_run_returns_result(monkeypatch):
    from tradingagents.rebalance import monthly_full as mf

    fake_graph = MagicMock()
    fake_graph.run.return_value = {
        "final_portfolio_path": "/tmp/portfolio_2026_06.json",
    }
    monkeypatch.setattr(mf, "TradingAgentsGraph", lambda: fake_graph)

    result = mf.run(month=6, as_of="2026-06-30")
    assert result.portfolio_path == "/tmp/portfolio_2026_06.json"
    assert result.report_path is None
    assert "Month 6" in result.summary
    fake_graph.run.assert_called_once()
    assert fake_graph.run.call_args.kwargs["as_of_date"] == "2026-06-30"


def test_monthly_run_uses_default_capital(monkeypatch):
    from tradingagents.rebalance import monthly_full as mf

    fake_graph = MagicMock()
    fake_graph.run.return_value = {"final_portfolio_path": "/tmp/p.json"}
    monkeypatch.setattr(mf, "TradingAgentsGraph", lambda: fake_graph)

    mf.run(month=7, as_of="2026-07-31")
    capital = fake_graph.run.call_args.kwargs["capital_krw"]
    assert capital >= 100_000_000  # sane default
