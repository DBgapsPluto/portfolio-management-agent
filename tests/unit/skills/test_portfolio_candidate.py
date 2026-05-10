from datetime import date

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates


def _build_universe() -> Universe:
    return Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A069500", name="KODEX 200", aum_krw=10e12,
                 underlying_index="x", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A360750", name="TIGER S&P500", aum_krw=15e12,
                 underlying_index="y", bucket="위험", category="해외주식_지수"),
        ETFEntry(ticker="A114260", name="KODEX 국고채3년", aum_krw=5e12,
                 underlying_index="z", bucket="안전", category="국내채권_종합"),
        ETFEntry(ticker="A459580", name="KODEX CD금리", aum_krw=8e12,
                 underlying_index="w", bucket="안전", category="금리연계형/초단기채권"),
        ETFEntry(ticker="A411060", name="ACE KRX금현물", aum_krw=5e12,
                 underlying_index="v", bucket="위험", category="FX 및 원자재"),
    ])


def test_select_candidates_for_target():
    target = BucketTarget(
        kr_equity=0.15, global_equity=0.30, fx_commodity=0.10,
        bond=0.35, cash_mmf=0.10,
        rationale="defensive recession tilt",
    )
    candidates = select_etf_candidates(
        _build_universe(), target, momentum_rankings={},
        as_of=date(2026, 5, 10),
    )
    assert "A069500" in candidates.bucket_to_tickers["kr_equity"]
    assert "A360750" in candidates.bucket_to_tickers["global_equity"]
    assert "A114260" in candidates.bucket_to_tickers["bond"]
    assert "A459580" in candidates.bucket_to_tickers["cash_mmf"]


def test_select_skips_unlisted_etf_for_past_as_of():
    """D13 survivorship: ETF listed in 2027 must be skipped for as_of=2026."""
    universe = Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A069500", name="KODEX 200", aum_krw=10e12,
                 underlying_index="x", bucket="위험", category="국내주식_지수",
                 listed_since=date(2020, 1, 1)),
        ETFEntry(ticker="A999999", name="Future ETF", aum_krw=10e12,
                 underlying_index="x", bucket="위험", category="국내주식_지수",
                 listed_since=date(2027, 1, 1)),
    ])
    target = BucketTarget(
        kr_equity=1.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.0,
        rationale="test",
    )
    candidates = select_etf_candidates(
        universe, target, momentum_rankings={},
        as_of=date(2026, 5, 10),
    )
    assert "A069500" in candidates.bucket_to_tickers["kr_equity"]
    assert "A999999" not in candidates.bucket_to_tickers["kr_equity"]
