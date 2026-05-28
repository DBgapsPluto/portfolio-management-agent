"""Regression tests for Tier 1: AUM filter removal from candidate_selector."""
import inspect
from datetime import date

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.skills.portfolio.candidate_selector import _eligible_for_bucket


def _make_universe(etfs):
    return Universe(version="t", etfs=etfs)


def test_aum_filter_removed_small_etfs_pass():
    """After Tier 1: small AUM ETFs are eligible (no filter)."""
    universe = _make_universe([
        ETFEntry(ticker="A100001", name="BIG", aum_krw=1_000_000_000_000,
                 underlying_index="u1", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A100002", name="SMALL", aum_krw=50_000_000_000,
                 underlying_index="u2", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A100003", name="TINY", aum_krw=10_000_000_000,
                 underlying_index="u3", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A100004", name="MICRO", aum_krw=1_000_000_000,
                 underlying_index="u4", bucket="위험", category="국내주식_지수"),
    ])

    eligible = _eligible_for_bucket(universe, ["국내주식_지수"])
    assert len(eligible) == 4  # all 4 pass (no AUM filter)
    tickers = [e.ticker for e in eligible]
    assert "A100003" in tickers and "A100004" in tickers  # TINY and MICRO pass


def test_eligible_for_bucket_signature_no_min_aum_param():
    """Verify _eligible_for_bucket no longer accepts min_aum_krw param."""
    sig = inspect.signature(_eligible_for_bucket)
    assert "min_aum_krw" not in sig.parameters


def test_eligible_for_bucket_category_mismatch_excluded():
    """ETFs in wrong category are still excluded."""
    universe = _make_universe([
        ETFEntry(ticker="A111111", name="A", aum_krw=1_000_000_000_000,
                 underlying_index="u1", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A222222", name="B", aum_krw=1_000_000_000_000,
                 underlying_index="u2", bucket="안전", category="국내채권_종합"),
    ])
    eligible = _eligible_for_bucket(universe, ["국내주식_지수"])
    tickers = [e.ticker for e in eligible]
    assert tickers == ["A111111"]
    assert "A222222" not in tickers


def test_eligible_for_bucket_empty_universe():
    """Empty universe returns empty list."""
    universe = _make_universe([])
    assert _eligible_for_bucket(universe, ["국내주식_지수"]) == []
