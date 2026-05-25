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


@pytest.fixture
def transactions_csv(tmp_path: Path) -> Path:
    """MTS-style transactions for June with ~12% monthly turnover."""
    df = pd.DataFrame({
        "거래일자": [
            "2026-06-02", "2026-06-03", "2026-06-15", "2026-06-20",
        ],
        "거래금액": [80_000_000, 20_000_000, 15_000_000, 5_000_000],
    })
    p = tmp_path / "transactions.csv"
    df.to_csv(p, index=False)
    return p


def test_generate_monthly_without_transactions_keeps_backward_compat(
    pnl_csv: Path,
):
    """transactions_csv 미제공 시 prompt에 '(not provided)' 명시되고 동작."""
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "본문"
    generate_monthly({"macro_summary": "m", "risk_summary": "r"},
                     pnl_csv, month=6, deep_llm=deep_llm)
    prompt = deep_llm.invoke.call_args[0][0]
    assert "Turnover (대회 §3):" in prompt
    assert "(not provided" in prompt


def test_generate_monthly_with_transactions_injects_numbers(
    pnl_csv: Path, transactions_csv: Path,
):
    """transactions_csv 제공 시 prompt에 실제 회전율 %와 §3.2 verdict 포함."""
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "본문"
    state = {
        "macro_summary": "m",
        "risk_summary": "r",
        "capital_krw": 1_000_000_000,
        "as_of_date": "2026-06-30",
    }
    generate_monthly(state, pnl_csv, month=6, deep_llm=deep_llm,
                     transactions_csv=transactions_csv)
    prompt = deep_llm.invoke.call_args[0][0]

    # 4건 합 = 120M / 1B = 12% → §3.2 충족
    assert "12.00%" in prompt or "12.0%" in prompt
    assert "충족" in prompt
    assert "§3.2" in prompt
    # 초기 세팅 회전율 (6/1-6/8): 2건 = 100M / 1B = 10%
    assert "10.00%" in prompt
    assert "§3.1" in prompt


def test_generate_monthly_with_transactions_flags_under_floor(
    tmp_path: Path, pnl_csv: Path,
):
    """월별 회전율 floor 미달 시 '미달' verdict + warning 노출."""
    df = pd.DataFrame({
        "거래일자": ["2026-07-05"],
        "거래금액": [50_000_000],  # 5% — floor 10% 미달
    })
    tx = tmp_path / "tx_low.csv"
    df.to_csv(tx, index=False)

    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "본문"
    state = {
        "capital_krw": 1_000_000_000,
        "as_of_date": "2026-07-31",
    }
    generate_monthly(state, pnl_csv, month=7, deep_llm=deep_llm,
                     transactions_csv=tx)
    prompt = deep_llm.invoke.call_args[0][0]

    assert "5.00%" in prompt
    assert "미달" in prompt
    assert "CUTOFF RISK" in prompt  # compute_turnover warnings
