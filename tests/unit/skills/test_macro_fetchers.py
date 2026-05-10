from datetime import date
from unittest.mock import patch
import pandas as pd

from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill


def test_fred_skill_wraps_dataflow():
    fake = pd.Series([4.5], index=[pd.Timestamp("2026-05-10")], name="DGS10")
    with patch("tradingagents.skills.macro.fred_fetcher.fetch_fred_series", return_value=fake):
        s = fetch_fred_series_skill("us_10y", date(2026, 5, 10), date(2026, 5, 10))
    assert s.iloc[-1] == 4.5


def test_ecos_skill_wraps_dataflow():
    fake = pd.Series([3.5], index=[pd.Timestamp("2026-05-01")])
    with patch("tradingagents.skills.macro.ecos_fetcher.fetch_ecos_series", return_value=fake):
        s = fetch_ecos_series_skill("kr_base_rate", date(2026, 5, 1), date(2026, 5, 31))
    assert s.iloc[-1] == 3.5
