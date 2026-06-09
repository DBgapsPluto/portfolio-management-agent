import json
from pathlib import Path
from tradingagents.dataflows.equity_indices import EQUITY_INDEX_TICKERS
from tradingagents.dataflows.fred import FRED_SERIES
from tradingagents.default_config import DEFAULT_CONFIG


def test_planc_equity_tickers():
    for k, v in [("vnq", "VNQ"), ("xlre", "XLRE"), ("schh", "SCHH"),
                 ("hyg", "HYG"), ("jnk", "JNK")]:
        assert EQUITY_INDEX_TICKERS.get(k) == v


def test_mortgage_fred():
    assert FRED_SERIES.get("us_mortgage_30y") == "MORTGAGE30US"
    assert DEFAULT_CONFIG["publication_lag_days"].get("us_mortgage_30y") == 7


def test_kr_reit_in_universe():
    u = json.loads(Path("data/universe.json").read_text(encoding="utf-8"))
    etfs = u.get("etfs", u if isinstance(u, list) else [])
    tickers = {e["ticker"] for e in etfs}
    assert "A329200" in tickers
    assert "A476800" in tickers
