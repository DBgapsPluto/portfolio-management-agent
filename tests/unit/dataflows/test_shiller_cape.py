import io, pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.dataflows.shiller_cape import (
    fetch_shiller_cape, _decimal_year_to_date,
)


def test_decimal_year_conversion():
    assert _decimal_year_to_date(1871.01) == pd.Timestamp(1871, 1, 1)
    assert _decimal_year_to_date(2026.04) == pd.Timestamp(2026, 4, 1)
    assert _decimal_year_to_date(2026.12) == pd.Timestamp(2026, 12, 1)


def test_fetch_shiller_cape_parses_excel(monkeypatch):
    """Mock urllib + verify CAPE column extracted, decimal year converted."""
    fake_df = pd.DataFrame({
        "Date": [2020.01, 2020.02, 2020.03],
        "CAPE": [30.5, 31.2, 28.7],
    })
    with patch("tradingagents.dataflows.shiller_cape.urllib.request.urlopen"), \
         patch("tradingagents.dataflows.shiller_cape.pd.read_excel", return_value=fake_df):
        result = fetch_shiller_cape(as_of=date(2020, 3, 31))
    assert len(result) == 3
    assert result.iloc[0] == 30.5
    assert isinstance(result.index[0], pd.Timestamp)
    assert result.index[0].year == 2020


def test_fetch_shiller_cape_as_of_truncates(monkeypatch):
    fake_df = pd.DataFrame({
        "Date": [2020.01, 2020.02, 2020.03],
        "CAPE": [30.5, 31.2, 28.7],
    })
    with patch("tradingagents.dataflows.shiller_cape.urllib.request.urlopen"), \
         patch("tradingagents.dataflows.shiller_cape.pd.read_excel", return_value=fake_df):
        result = fetch_shiller_cape(as_of=date(2020, 2, 15))
    assert len(result) <= 2  # Jan + Feb only


@pytest.mark.network
def test_fetch_shiller_cape_live():
    """Hits actual Yale URL — gated by @pytest.mark.network."""
    from datetime import date as _date
    s = fetch_shiller_cape(as_of=_date(2025, 1, 1))
    assert len(s) > 100
    assert s.index[0].year == 1881  # CAPE valid from 1881
    assert all(s > 0)
