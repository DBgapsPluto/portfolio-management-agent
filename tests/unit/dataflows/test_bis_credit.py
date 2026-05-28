import pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.dataflows.bis_credit import (
    fetch_bis_china_credit, _find_bis_code_position,
    BIS_CN_CREDIT_CODE,
)


def test_find_bis_code_position_locates_code():
    df = pd.DataFrame({
        0: ["", "", "", "Q:CN:P:A:M:770:A", ""],
        1: ["", "", "", "OtherCode", ""],
    })
    row, col = _find_bis_code_position(df, "Q:CN:P:A:M:770:A")
    assert row == 3
    assert col == 0


def test_find_bis_code_not_found():
    df = pd.DataFrame({0: ["", "", "Code1"]})
    row, col = _find_bis_code_position(df, "NotPresent")
    assert row is None and col is None


def test_fetch_bis_china_credit_raises_on_missing_code():
    # header_df doesn't contain the code at all
    fake_header_df = pd.DataFrame({0: ["title", "other_code", "more"]})
    with patch("tradingagents.dataflows.bis_credit._raw_bis_fetch", return_value=b""), \
         patch("tradingagents.dataflows.bis_credit.pd.read_excel",
               return_value=fake_header_df):
        with pytest.raises(ValueError, match="not found"):
            fetch_bis_china_credit()


def test_bis_constant_matches_spec():
    assert BIS_CN_CREDIT_CODE == "Q:CN:P:A:M:770:A"


@pytest.mark.network
def test_fetch_bis_china_credit_live():
    """Live BIS xlsx — gated by @pytest.mark.network."""
    s = fetch_bis_china_credit(as_of=date(2023, 12, 31))
    assert len(s) > 100  # quarterly, 1985+ → 150+ rows
    assert s.iloc[-1] > 100  # China credit/GDP > 100% in recent years
