from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from tradingagents.reports.monthly import generate_monthly, write_monthly


@pytest.fixture
def pnl_csv(tmp_path: Path) -> Path:
    df = pd.DataFrame({
        "date": pd.date_range("2026-06-01", periods=21, freq="B"),
        "equity": [1_000_000_000 + i * 1_000_000 for i in range(21)],
    })
    p = tmp_path / "pnl.csv"
    df.to_csv(p, index=False)
    return p


def test_generate_monthly_returns_llm_content(pnl_csv: Path):
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "월간보고서 본문 " * 200
    state = {"macro_summary": "regime: expansion", "risk_summary": "VIX 18"}
    text = generate_monthly(state, pnl_csv, month=6, deep_llm=deep_llm)
    assert "월간보고서" in text
    # Verify the prompt got pnl + state injected
    call_args = deep_llm.invoke.call_args[0][0]
    assert "Starting equity" in call_args
    assert "Macro: regime: expansion" in call_args
    assert "{month}" not in call_args  # template was rendered


def test_write_monthly_creates_file(tmp_path: Path, pnl_csv: Path):
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "월간 본문"
    out = tmp_path / "monthly.md"
    result = write_monthly({}, pnl_csv, 6, deep_llm, out)
    assert result == out
    assert out.read_text(encoding="utf-8") == "월간 본문"
