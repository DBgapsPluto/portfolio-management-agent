"""external_fetchers.py: yfinance KRW + S&P trailing P/E fetchers (mock yfinance)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingagents.skills.research import external_fetchers


@pytest.fixture(autouse=True)
def _reset_caches():
    external_fetchers.reset_cache()
    yield
    external_fetchers.reset_cache()


def _mk_hist_with_close(value: float | None) -> pd.DataFrame:
    if value is None:
        return pd.DataFrame()
    return pd.DataFrame({"Close": [value]}, index=pd.to_datetime(["2026-05-22"]))


@patch("tradingagents.skills.research.external_fetchers.yf.Ticker")
def test_fetch_krw_usd_level_success(mock_ticker_cls):
    inst = MagicMock()
    inst.history.return_value = _mk_hist_with_close(1380.5)
    mock_ticker_cls.return_value = inst

    val = external_fetchers.fetch_krw_usd_level()

    assert val == pytest.approx(1380.5)
    mock_ticker_cls.assert_called_once_with("KRW=X")


@patch("tradingagents.skills.research.external_fetchers.yf.Ticker")
def test_fetch_krw_usd_level_empty_hist(mock_ticker_cls):
    inst = MagicMock()
    inst.history.return_value = pd.DataFrame()
    mock_ticker_cls.return_value = inst

    assert external_fetchers.fetch_krw_usd_level() is None


@patch("tradingagents.skills.research.external_fetchers.yf.Ticker")
def test_fetch_krw_usd_level_exception(mock_ticker_cls):
    mock_ticker_cls.side_effect = RuntimeError("network down")

    assert external_fetchers.fetch_krw_usd_level() is None


@patch("tradingagents.skills.research.external_fetchers.yf.Ticker")
def test_fetch_sp_trailing_pe_success(mock_ticker_cls):
    inst = MagicMock()
    inst.info = {"trailingPE": 24.7}
    mock_ticker_cls.return_value = inst

    val = external_fetchers.fetch_sp_trailing_pe()

    assert val == pytest.approx(24.7)
    mock_ticker_cls.assert_called_once_with("SPY")


@patch("tradingagents.skills.research.external_fetchers.yf.Ticker")
def test_fetch_sp_trailing_pe_missing_key(mock_ticker_cls):
    inst = MagicMock()
    inst.info = {"someOtherField": 1}
    mock_ticker_cls.return_value = inst

    assert external_fetchers.fetch_sp_trailing_pe() is None
