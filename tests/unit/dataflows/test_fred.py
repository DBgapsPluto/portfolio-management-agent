from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.fred import FRED_SERIES, fetch_funding_stress_stitched

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


def test_stitch_uses_ted_pre_2018():
    ted = pd.Series(
        [25.0, 30.0, 28.0],
        index=pd.to_datetime(["2010-01-01", "2010-02-01", "2010-03-01"]),
    )
    def mock_fred(key, *args, **kwargs):
        if key == "ted_spread":
            return ted
        return pd.Series(dtype=float)
    with patch("tradingagents.dataflows.fred.fetch_fred_series", side_effect=mock_fred):
        s = fetch_funding_stress_stitched(date(2010, 1, 1), date(2010, 3, 31))
    assert len(s) == 3
    assert s.iloc[0] == 25.0


def test_stitch_uses_sofr_post_2018():
    sofr = pd.Series([2.0, 2.1], index=pd.to_datetime(["2020-01-01", "2020-02-01"]))
    tbill = pd.Series([1.9, 1.95], index=pd.to_datetime(["2020-01-01", "2020-02-01"]))
    def mock_fred(key, *args, **kwargs):
        if key == "us_sofr":
            return sofr
        if key == "us_3m_tbill":
            return tbill
        return pd.Series(dtype=float)
    with patch("tradingagents.dataflows.fred.fetch_fred_series", side_effect=mock_fred):
        s = fetch_funding_stress_stitched(date(2020, 1, 1), date(2020, 2, 28))
    assert len(s) == 2
    # (SOFR - tbill) * 100 = (2.0-1.9)*100 = 10 bps
    assert abs(s.iloc[0] - 10.0) < 0.01


def test_stitch_overlap_period_excludes_ted_after_2018_04_03():
    """Defensive: TED rows after boundary should not appear in stitched output."""
    ted = pd.Series(
        [25.0, 26.0, 27.0],
        index=pd.to_datetime(["2018-03-01", "2018-04-01", "2018-04-15"]),
    )
    sofr = pd.Series([2.0], index=pd.to_datetime(["2018-04-15"]))
    tbill = pd.Series([1.9], index=pd.to_datetime(["2018-04-15"]))
    def mock_fred(key, *args, **kwargs):
        if key == "ted_spread":
            return ted
        if key == "us_sofr":
            return sofr
        if key == "us_3m_tbill":
            return tbill
        return pd.Series(dtype=float)
    with patch("tradingagents.dataflows.fred.fetch_fred_series", side_effect=mock_fred):
        s = fetch_funding_stress_stitched(date(2018, 3, 1), date(2018, 4, 30))
    # TED 2018-03-01 (kept), 2018-04-01 (before boundary 2018-04-03 kept),
    # 2018-04-15 should be from SOFR (not TED)
    assert pd.Timestamp("2018-03-01") in s.index
    # 2018-04-15 should be SOFR-Tbill = (2.0-1.9)*100 = 10.0 bps
    assert abs(s.loc[pd.Timestamp("2018-04-15")] - 10.0) < 0.01
