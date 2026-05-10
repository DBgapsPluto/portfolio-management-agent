from datetime import date
from unittest.mock import MagicMock, patch
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.agents.analysts.technical_analyst import create_technical_analyst
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.reports import TechnicalReport


def _synthetic_prices(tickers: list, n: int = 250) -> pd.DataFrame:
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
