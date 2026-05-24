"""compute_kospi_valuation tests (C5 — factor model F8 valuation component).

D7 pattern (신규 class indicator): full Snapshot return (analyst 가 MacroReport
의 Optional field 에 직접 채움; model_copy 아님).
D8 pattern: empty / exception → None (graceful skip, no default fill, no raise).
D9 pattern: no retry, no cache in skill — fresh compute each call.
"""
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.schemas.macro import KRValuationSnapshot
from tradingagents.skills.macro.kr_valuation import compute_kospi_valuation


def test_kospi_valuation_returns_snapshot():
    mock_df = pd.DataFrame({
        "PBR": [0.95], "PER": [11.5], "DIV": [2.1],
    })
    with patch(
        "tradingagents.skills.macro.kr_valuation.stock.get_market_fundamental",
        return_value=mock_df,
    ):
        result = compute_kospi_valuation(as_of=date(2026, 5, 15))

    assert isinstance(result, KRValuationSnapshot)
    assert result.kospi_pbr == pytest.approx(0.95)
    assert result.kospi_per == pytest.approx(11.5)
    assert result.kospi_div_yield == pytest.approx(2.1)


def test_kospi_valuation_multiple_rows_averaged():
    mock_df = pd.DataFrame({
        "PBR": [0.9, 1.0, 1.1], "PER": [10, 12, 14], "DIV": [2.0, 2.0, 2.0],
    })
    with patch(
        "tradingagents.skills.macro.kr_valuation.stock.get_market_fundamental",
        return_value=mock_df,
    ):
        result = compute_kospi_valuation(as_of=date(2026, 5, 15))

    assert result.kospi_pbr == pytest.approx(1.0)  # mean of 0.9, 1.0, 1.1
    assert result.kospi_per == pytest.approx(12.0)


def test_kospi_valuation_empty_df_returns_none():
    empty_df = pd.DataFrame({"PBR": [], "PER": [], "DIV": []})
    with patch(
        "tradingagents.skills.macro.kr_valuation.stock.get_market_fundamental",
        return_value=empty_df,
    ):
        result = compute_kospi_valuation(as_of=date(2026, 5, 15))

    assert result is None  # D8 graceful None


def test_kospi_valuation_pykrx_exception_returns_none():
    with patch(
        "tradingagents.skills.macro.kr_valuation.stock.get_market_fundamental",
        side_effect=Exception("pykrx error"),
    ):
        result = compute_kospi_valuation(as_of=date(2026, 5, 15))

    assert result is None
