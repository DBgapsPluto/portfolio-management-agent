from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingagents.agents.analysts.macro_quant_analyst import create_macro_quant_analyst
from tradingagents.schemas.macro import RegimeClassification
from tradingagents.schemas.reports import MacroReport


def test_macro_analyst_orchestration(monkeypatch):
    quick_llm = MagicMock()
    deep_llm = MagicMock()

    # Mock the regime subagent via the LLM's structured output
    regime_out = RegimeClassification(
        quadrant="recession_disinflation", confidence=0.8,
        drivers=["yield curve"], reasoning="x",
        source_date=date(2026, 5, 10),
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = regime_out

    # Mock all fetchers via monkeypatch
    fake_yield = pd.Series(
        [4.5, 4.4], index=pd.date_range("2026-05-08", periods=2)
    )
    fake_cpi = pd.Series(
        [305.0] * 14, index=pd.date_range("2025-04-01", periods=14, freq="MS")
    )
    fake_ur = pd.Series(
        [4.2] * 15, index=pd.date_range("2025-03-01", periods=15, freq="MS")
    )

    def fake_fred(series, start, end, **kwargs):
        if "10y" in series or "2y" in series or "3m" in series or "policy" in series:
            return fake_yield
        if "cpi" in series:
            return fake_cpi
        if "unrate" in series or "payems" in series:
            return fake_ur
        return fake_yield

    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_quant_analyst.fetch_fred_series_skill",
        fake_fred,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_quant_analyst.fetch_ecos_series_skill",
        fake_fred,
    )

    quick_llm.invoke.return_value.content = "macro narrative ≤500 chars"

    node = create_macro_quant_analyst(quick_llm, deep_llm)
    state = {"as_of_date": "2026-05-10"}
    result = node(state)
    assert "macro_report" in result
    assert isinstance(result["macro_report"], MacroReport)
    assert result["macro_report"].regime.quadrant == "recession_disinflation"
    assert "macro_summary" in result
    assert len(result["macro_summary"]) <= 2000
