import pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.dataflows.gz_ebp import fetch_gz_ebp


_FAKE_CSV_BYTES = (
    b"date,gz_spread,ebp,est_prob\n"
    b"2020-01-01,1.5,-0.04,0.18\n"
    b"2020-02-01,2.1,0.45,0.32\n"
    b"2020-03-01,5.5,3.20,0.85\n"
)


def test_fetch_gz_ebp_parses_csv():
    with patch("tradingagents.dataflows.gz_ebp._raw_gz_ebp_fetch",
               return_value=_FAKE_CSV_BYTES):
        s = fetch_gz_ebp(as_of=date(2020, 3, 31))
    assert len(s) == 3
    assert s.iloc[2] == 3.20
    assert s.name == "ebp"


def test_fetch_gz_ebp_as_of_truncates():
    with patch("tradingagents.dataflows.gz_ebp._raw_gz_ebp_fetch",
               return_value=_FAKE_CSV_BYTES):
        s = fetch_gz_ebp(as_of=date(2020, 1, 15))
    assert len(s) == 1
    assert s.index[0] == pd.Timestamp(2020, 1, 1)


@pytest.mark.network
def test_fetch_gz_ebp_live():
    s = fetch_gz_ebp(as_of=date(2025, 1, 1))
    assert len(s) > 500  # 1973+ → 600+ months by 2025
    assert s.index[0].year == 1973
