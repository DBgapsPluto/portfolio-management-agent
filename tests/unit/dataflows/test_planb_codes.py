from tradingagents.dataflows.equity_indices import EQUITY_INDEX_TICKERS
from tradingagents.dataflows.fred import FRED_SERIES
from tradingagents.dataflows.ecos import ECOS_STAT_CODES
from tradingagents.default_config import DEFAULT_CONFIG


def test_equity_index_tickers():
    assert EQUITY_INDEX_TICKERS.get("sox") == "^SOX"
    assert EQUITY_INDEX_TICKERS.get("smh") == "SMH"
    assert EQUITY_INDEX_TICKERS.get("eem") == "EEM"
    assert EQUITY_INDEX_TICKERS.get("emb") == "EMB"
    assert EQUITY_INDEX_TICKERS.get("vwo") == "VWO"


def test_chip_ppi_fred():
    assert FRED_SERIES.get("us_chip_ppi") == "PCU334413334413"
    assert DEFAULT_CONFIG["publication_lag_days"].get("us_chip_ppi") == 30


def test_kr_sector_export_ecos():
    for key, item in [
        ("kr_export_semi", "30911AA"), ("kr_export_battery", "31013AA"),
        ("kr_export_display", "30921AA"), ("kr_export_chem", "305AA"),
        ("kr_export_steel", "3071AA"),
    ]:
        assert key in ECOS_STAT_CODES
        stat, code = ECOS_STAT_CODES[key]
        assert stat == "403Y002"
        assert code == item
