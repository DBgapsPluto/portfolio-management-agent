import pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.agents.analysts.market_risk_analyst import _build_excess_bond_premium


def test_build_ebp_returns_snapshot():
    fake_series = pd.Series(
        [-0.04, 0.05, 0.10, 0.20, 0.25] * 24,  # 120 months
        index=pd.date_range("2016-01-01", periods=120, freq="MS"),
    )
    with patch("tradingagents.agents.analysts.market_risk_analyst.fetch_gz_ebp",
               return_value=fake_series):
        snap = _build_excess_bond_premium(date(2026, 1, 1))
    assert snap is not None
    assert snap.ebp_zscore_5y is not None


def test_build_ebp_returns_none_on_empty():
    with patch("tradingagents.agents.analysts.market_risk_analyst.fetch_gz_ebp",
               return_value=pd.Series(dtype=float)):
        snap = _build_excess_bond_premium(date(2026, 1, 1))
    assert snap is None


def test_build_ebp_returns_none_on_exception():
    with patch("tradingagents.agents.analysts.market_risk_analyst.fetch_gz_ebp",
               side_effect=Exception("network error")):
        snap = _build_excess_bond_premium(date(2026, 1, 1))
    assert snap is None
