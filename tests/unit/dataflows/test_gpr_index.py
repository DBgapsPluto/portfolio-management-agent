import pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.dataflows.gpr_index import fetch_gpr_index


def test_fetch_gpr_monthly():
    fake_df = pd.DataFrame({
        "month": pd.to_datetime(["2020-01-01", "2020-02-01"]),
        "GPR": [85.0, 92.5],
        "GPRC_KOR": [40.0, 45.0],
    })
    with patch("tradingagents.dataflows.gpr_index._raw_gpr_fetch", return_value=b""), \
         patch("tradingagents.dataflows.gpr_index.pd.read_excel", return_value=fake_df):
        s = fetch_gpr_index(frequency="monthly", series="GPR",
                            as_of=date(2020, 2, 28))
    assert len(s) == 2
    assert s.iloc[0] == 85.0
    assert s.name == "gpr"


def test_fetch_gpr_country_specific_kor():
    fake_df = pd.DataFrame({
        "month": pd.to_datetime(["2020-01-01"]),
        "GPR": [85.0],
        "GPRC_KOR": [40.0],
    })
    with patch("tradingagents.dataflows.gpr_index._raw_gpr_fetch", return_value=b""), \
         patch("tradingagents.dataflows.gpr_index.pd.read_excel", return_value=fake_df):
        s = fetch_gpr_index(series="GPRC_KOR")
    assert s.iloc[0] == 40.0


def test_fetch_gpr_unknown_series_fallback():
    """Unknown series name falls back to default 'GPR'."""
    fake_df = pd.DataFrame({
        "month": pd.to_datetime(["2020-01-01"]),
        "GPR": [85.0],
    })
    with patch("tradingagents.dataflows.gpr_index._raw_gpr_fetch", return_value=b""), \
         patch("tradingagents.dataflows.gpr_index.pd.read_excel", return_value=fake_df):
        s = fetch_gpr_index(series="GPR_NONEXISTENT")
    assert s.iloc[0] == 85.0  # falls back to GPR


@pytest.mark.network
def test_fetch_gpr_monthly_live():
    """Live fetch from Iacoviello — gated by @pytest.mark.network."""
    s = fetch_gpr_index(frequency="monthly", series="GPR", as_of=date(2025, 1, 1))
    assert len(s) > 400  # monthly since 1985 → 480+ rows through 2025-01
    assert s.index[0].year <= 1986  # data starts 1985
    assert all(s > 0)
