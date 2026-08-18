from datetime import date
from unittest.mock import MagicMock, patch
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.agents.analysts.technical_analyst import create_technical_analyst
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.reports import TechnicalReport


def _synthetic_prices(tickers: list, n: int = 300) -> pd.DataFrame:
    # 274 = 252 (12m) + 21 (skip-1m) + 1 buffer — rank_momentum._MIN_HISTORY_DAYS.
    # 300 으로 안전 마진. 이전 260일 → asset_class_momentum 빈 dict 회귀.
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    rows = []
    for ticker in tickers:
        close = 100 + np.cumsum(rng.normal(0.5, 1.0, n))
        for d, c in zip(dates, close):
            rows.append({
                "ticker": ticker, "date": d, "close": float(c),
                "open": float(c-0.5), "high": float(c+1), "low": float(c-1), "volume": 1000,
            })
    return pd.DataFrame(rows)


def _synthetic_prices_var(history_days: dict[str, int], n: int = 300) -> pd.DataFrame:
    """_synthetic_prices variant: per-ticker history length (last `days` of the
    shared business-day calendar). Short-history tickers discriminate the F5
    cluster pools — full-universe (>=126d) vs top-tier dropna(how='any')."""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    rng = np.random.default_rng(42)
    rows = []
    for ticker, days in history_days.items():
        close = 100 + np.cumsum(rng.normal(0.5, 1.0, days))
        for d, c in zip(dates[-days:], close):
            rows.append({
                "ticker": ticker, "date": d, "close": float(c),
                "open": float(c-0.5), "high": float(c+1), "low": float(c-1), "volume": 1000,
            })
    return pd.DataFrame(rows)


_FULL_TICKERS = ["A069500", "A360750", "A411060", "A114260"]
_SHORT_TICKER = "A459580"    # 150d: >=126 returns (dial-ON pool) but NaN inside
                             # the 252d window + unrankable (dial-OFF pool excludes)


def _run_node_with_cluster_spy(tmp_path, portfolio_dials):
    """Run the technical analyst with find_correlation_clusters spied.

    Returns (captured, result): captured["columns"] = cluster-input columns,
    captured["kwargs"] = extra kwargs beyond (returns, threshold, universe_lookup).
    """
    from tradingagents.agents.analysts import technical_analyst as ta_mod
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    quick_llm.invoke.return_value.content = "technical narrative"
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    history = {t: 300 for t in _FULL_TICKERS}
    history[_SHORT_TICKER] = 150
    fake_prices = _synthetic_prices_var(history)

    real = ta_mod.find_correlation_clusters
    captured: dict = {}

    def spy(returns, threshold=0.7, universe_lookup=None, **kwargs):
        captured["columns"] = list(returns.columns)
        captured["kwargs"] = dict(kwargs)
        return real(returns, threshold=threshold, universe_lookup=universe_lookup, **kwargs)

    state = {"as_of_date": "2026-05-10", "universe_path": str(universe_json)}
    if portfolio_dials is not None:
        state["portfolio_dials"] = portfolio_dials
    with patch("tradingagents.agents.analysts.technical_analyst.fetch_etf_price_batch",
               return_value=fake_prices), \
         patch("tradingagents.agents.analysts.technical_analyst.find_correlation_clusters",
               side_effect=spy):
        node = create_technical_analyst(quick_llm, deep_llm)
        result = node(state)
    return captured, result


def test_cluster_dial_off_keeps_top_tier_pool_and_default_linkage(tmp_path):
    """cluster_full_universe absent/False (bare state, like all callers today):
    the cluster input stays the top-tier dropna pool and the skill is invoked
    without the new kwargs — byte-identical production path (F5/D1-1)."""
    captured, result = _run_node_with_cluster_spy(tmp_path, portfolio_dials=None)
    assert captured["kwargs"] == {}                       # no linkage/min_periods passed
    assert _SHORT_TICKER not in captured["columns"]       # NaN-in-window ticker dropped
    assert set(captured["columns"]) <= set(_FULL_TICKERS)
    assert "correlation_clusters" in result


def test_cluster_dial_on_full_pool_complete_linkage(tmp_path):
    """cluster_full_universe=True: pool = every ticker with >=126d of returns
    (short-history ticker included), complete linkage + min_periods=126 —
    the D0-2 decision (F5/D1-1)."""
    captured, result = _run_node_with_cluster_spy(
        tmp_path, portfolio_dials={"cluster_full_universe": True})
    assert captured["kwargs"] == {"linkage_method": "complete", "min_periods": 126}
    assert _SHORT_TICKER in captured["columns"]           # >=126d -> eligible
    assert set(captured["columns"]) == set(_FULL_TICKERS) | {_SHORT_TICKER}
    assert "correlation_clusters" in result


def test_technical_analyst_returns_report(tmp_path):
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    quick_llm.invoke.return_value.content = "technical narrative"

    # Build a small universe.json from the test fixture
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    fake_tickers = ["A069500", "A360750", "A411060", "A114260", "A459580"]
    fake_prices = _synthetic_prices(fake_tickers)

    with patch("tradingagents.agents.analysts.technical_analyst.fetch_etf_price_batch",
               return_value=fake_prices):
        node = create_technical_analyst(quick_llm, deep_llm)
        result = node({
            "as_of_date": "2026-05-10",
            "universe_path": str(universe_json),
        })

    assert "technical_report" in result
    assert isinstance(result["technical_report"], TechnicalReport)
    assert "correlation_clusters" in result
    assert "technical_summary" in result
    assert len(result["technical_summary"]) <= 2000
    assert result["technical_report"].narrative == "technical narrative"
    assert len(result["technical_report"].asset_class_momentum) > 0
    assert len(result["technical_report"].individual_etf_states) > 0
