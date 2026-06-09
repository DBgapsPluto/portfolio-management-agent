from tradingagents.dataflows.fred import FRED_SERIES
from tradingagents.default_config import DEFAULT_CONFIG


def test_usd_jpy_registered():
    assert FRED_SERIES.get("usd_jpy") == "DEXJPUS"
    assert DEFAULT_CONFIG["publication_lag_days"].get("usd_jpy") == 1
