import json
from pathlib import Path
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS


def test_every_etf_has_valid_gaps_bucket():
    u = json.loads(Path("data/universe.json").read_text())
    etfs = u["etfs"]
    assert len(etfs) == 190
    for e in etfs:
        assert "gaps_bucket" in e, f"{e['ticker']} missing gaps_bucket"
        assert e["gaps_bucket"] in GAPS_BUCKET_KEYS, \
            f"{e['ticker']} bad gaps_bucket {e['gaps_bucket']}"


def test_etfentry_roundtrips_gaps_bucket():
    from tradingagents.dataflows.universe import ETFEntry
    e = ETFEntry(
        ticker="A459580", name="x", aum_krw=1.0, underlying_index="i",
        bucket="안전", category="c", gaps_bucket="a1_cash",
    )
    assert e.gaps_bucket == "a1_cash"
