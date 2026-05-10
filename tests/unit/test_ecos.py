from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.dataflows.ecos import fetch_ecos_series, ECOS_STAT_CODES


def test_known_codes_present():
    assert "kr_base_rate" in ECOS_STAT_CODES
    assert "kr_cpi" in ECOS_STAT_CODES
    assert "kr_m2" in ECOS_STAT_CODES


def test_fetch_returns_pandas():
    fake_payload = {
        "StatisticSearch": {
            "row": [
                {"TIME": "202604", "DATA_VALUE": "3.5", "ITEM_NAME1": "한국은행 기준금리"},
                {"TIME": "202605", "DATA_VALUE": "3.5", "ITEM_NAME1": "한국은행 기준금리"},
            ]
        }
    }
    with patch("tradingagents.dataflows.ecos._raw_ecos_call", return_value=fake_payload):
        s = fetch_ecos_series("kr_base_rate", date(2026, 4, 1), date(2026, 5, 31), api_key="dummy")
    assert len(s) == 2
    assert s.iloc[-1] == 3.5
