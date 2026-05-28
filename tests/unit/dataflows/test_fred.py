import pytest
from tradingagents.dataflows.fred import FRED_SERIES

NEW_TIER0_SERIES = {
    "us_indpro": "INDPRO",
    "us_real_pce": "PCECC96",       # Real PCE chained 2017 dollars (1947+)
    "us_acm_term_premium_10y": "THREEFYTP10",
    "kr_reer": "RBKRBIS",
    "ted_spread": "TEDRATE",
}

@pytest.mark.parametrize("key,series_id", NEW_TIER0_SERIES.items())
def test_tier0_fred_series_registered(key, series_id):
    assert key in FRED_SERIES
    assert FRED_SERIES[key] == series_id
