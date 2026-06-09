from tradingagents.dataflows.ecos import ECOS_STAT_CODES
from tradingagents.default_config import DEFAULT_CONFIG


def test_a2_series_registered():
    for key, item in [
        ("kr_treasury_5y", "010200001"),
        ("kr_treasury_30y", "010230000"),
        ("kr_corp_bbb_3y", "010320000"),
        ("kr_cd91", "010502000"),
    ]:
        assert key in ECOS_STAT_CODES, f"{key} missing"
        stat, code = ECOS_STAT_CODES[key]
        assert stat == "817Y002"
        assert code == item


def test_a2_publication_lag():
    lag = DEFAULT_CONFIG["publication_lag_days"]
    for key in ("kr_treasury_5y", "kr_treasury_30y", "kr_corp_bbb_3y", "kr_cd91"):
        assert lag.get(key) == 1
