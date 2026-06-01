import pytest
from unittest.mock import patch, MagicMock
from datetime import date
import pandas as pd
import numpy as np
from tradingagents.backtest.historical import bucket_returns_8b as b8


def test_kr_equity_tr_from_kospi200():
    fake = pd.DataFrame(
        {"종가": [380, 385, 388, 390]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]),
    )
    with patch("pykrx.stock.get_index_ohlcv_by_date", return_value=fake):
        s = b8._build_kr_equity_tr(date(2024, 1, 1), date(2024, 1, 31))
    assert not s.empty
    assert s.name == "kr_equity_tr"
    # 4 rows, first is NaN from pct_change (+div added -> still NaN since NaN+x=NaN)
    assert len(s) == 4


def test_kr_equity_empty_when_no_data():
    with patch("pykrx.stock.get_index_ohlcv_by_date", return_value=pd.DataFrame()):
        s = b8._build_kr_equity_tr(date(2024, 1, 1), date(2024, 1, 31))
    assert s.empty


def test_cash_mmf_from_ecos():
    fake_yield = pd.Series(
        [350.0, 351.0, 352.0],
        index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
    )
    with patch("tradingagents.dataflows.ecos.fetch_ecos_series", return_value=fake_yield):
        s = b8._build_cash_mmf_tr(date(2020, 1, 1), date(2020, 1, 31))
    assert not s.empty
    # daily TR = yield/36000 shifted; ~350/36000 ~= 0.0097
    assert s.iloc[0] == pytest.approx(350.0 / 36000, abs=1e-6)


def test_orchestrator_handles_builder_failure():
    """If a builder raises, orchestrator logs + emits empty col, still returns 8-col frame."""
    def boom(*a, **k):
        raise RuntimeError("env blocked")

    with patch.object(b8, "_build_kr_equity_tr", boom), \
         patch.object(b8, "_build_global_equity_tr", boom), \
         patch.object(b8, "_build_precious_metals_tr", boom), \
         patch.object(b8, "_build_cyclical_commodity_fx_tr", boom), \
         patch.object(b8, "_build_kr_bond_tr", boom), \
         patch.object(b8, "_build_credit_tr", boom), \
         patch.object(b8, "_build_global_duration_tr", boom), \
         patch.object(b8, "_build_cash_mmf_tr", boom):
        df = b8.build_bucket_returns_8b(date(2020, 1, 1), date(2020, 6, 30))
    assert list(df.columns) == [
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    ]


def test_orchestrator_quarterly_aggregation():
    """Daily returns compound to quarterly."""
    idx = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    fake_daily = pd.Series(0.001, index=idx)  # 0.1%/day

    def stub(*a, **k):
        return fake_daily.copy()

    with patch.object(b8, "_build_kr_equity_tr", stub), \
         patch.object(b8, "_build_global_equity_tr", stub), \
         patch.object(b8, "_build_precious_metals_tr", stub), \
         patch.object(b8, "_build_cyclical_commodity_fx_tr", stub), \
         patch.object(b8, "_build_kr_bond_tr", stub), \
         patch.object(b8, "_build_credit_tr", stub), \
         patch.object(b8, "_build_global_duration_tr", stub), \
         patch.object(b8, "_build_cash_mmf_tr", stub):
        df = b8.build_bucket_returns_8b(date(2020, 1, 1), date(2020, 3, 31))
    # Q1 2020 compound of ~91 days x 0.1% ~= (1.001^91 - 1) ~= 0.095
    assert df.shape[0] >= 1
    assert df["kr_equity"].iloc[0] == pytest.approx((1.001 ** len(idx)) - 1, rel=0.01)
